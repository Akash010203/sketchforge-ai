"""Cross-field and structural validation of a Design IR document.

Pydantic checks each field. This module checks what only the whole document can answer: a single
root, unique ids, existing parents, no cycles, and which boxes sit outside their parent or page.
Errors make a document invalid; warnings are layout findings the evaluator/repair engine handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sketchforge.constants import SCHEMA_VERSION
from sketchforge.design_ir.geometry import contains, intersection_area
from sketchforge.design_ir.schema import BBox, ComponentType, DesignDocument
from sketchforge.exceptions import DesignValidationError

_NO_TEXT_TYPES = {ComponentType.DIVIDER, ComponentType.IMAGE, ComponentType.PAGE}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    component_id: str | None = None

    def __str__(self) -> str:
        where = f" [{self.component_id}]" if self.component_id else ""
        return f"{self.code}{where}: {self.message}"


@dataclass
class ValidationReport:
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if self.errors:
            summary = "; ".join(str(e) for e in self.errors[:5])
            more = f" (+{len(self.errors) - 5} more)" if len(self.errors) > 5 else ""
            raise DesignValidationError(f"invalid design: {summary}{more}", report=self)

    def codes(self) -> set[str]:
        return {i.code for i in (*self.errors, *self.warnings)}

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "errors": [str(e) for e in self.errors],
            "warnings": [str(w) for w in self.warnings],
        }


def validate_document(doc: DesignDocument, *, tolerance_px: float = 1.0) -> ValidationReport:
    report = ValidationReport()
    err, warn = report.errors, report.warnings

    if doc.schema_version != SCHEMA_VERSION:
        err.append(
            ValidationIssue(
                "E_SCHEMA_VERSION",
                f"document is version {doc.schema_version}, application expects {SCHEMA_VERSION}",
            )
        )

    # ids -------------------------------------------------------------------------------
    seen: dict[str, int] = {}
    for comp in doc.components:
        seen[comp.id] = seen.get(comp.id, 0) + 1
    for cid, count in seen.items():
        if count > 1:
            err.append(ValidationIssue("E_DUPLICATE_ID", f"id used {count} times", cid))
    ids = set(seen)

    # root ------------------------------------------------------------------------------
    roots = [c for c in doc.components if c.parent_id is None]
    if len(roots) != 1:
        err.append(
            ValidationIssue("E_ROOT_COUNT", f"expected exactly one root, found {len(roots)}")
        )
    if doc.root_id not in ids:
        err.append(ValidationIssue("E_ROOT_MISSING", f"root_id {doc.root_id!r} not in components"))
    elif doc.require(doc.root_id).parent_id is not None:
        err.append(ValidationIssue("E_ROOT_PARENT", "root component must not have a parent", doc.root_id))

    # parents & cycles ---------------------------------------------------------------------
    for comp in doc.components:
        if comp.parent_id is not None and comp.parent_id not in ids:
            err.append(
                ValidationIssue("E_PARENT_MISSING", f"parent {comp.parent_id!r} does not exist", comp.id)
            )
        if comp.parent_id == comp.id:
            err.append(ValidationIssue("E_SELF_PARENT", "component is its own parent", comp.id))
        if comp.type is ComponentType.PAGE and comp.id != doc.root_id:
            err.append(ValidationIssue("E_PAGE_NOT_ROOT", "only the root may have type 'page'", comp.id))

    by_id = {c.id: c for c in doc.components}
    reachable: set[str] = set()
    for comp in doc.components:
        chain: list[str] = []
        cur = comp
        while True:
            if cur.id in chain:
                err.append(ValidationIssue("E_CYCLE", "parent chain forms a cycle", comp.id))
                break
            chain.append(cur.id)
            if cur.parent_id is None or cur.parent_id not in by_id:
                if cur.id == doc.root_id:
                    reachable.update(chain)
                break
            cur = by_id[cur.parent_id]
    for comp in doc.components:
        if comp.id not in reachable and not any(
            e.component_id == comp.id and e.code in {"E_PARENT_MISSING", "E_CYCLE"} for e in err
        ):
            err.append(ValidationIssue("E_UNREACHABLE", "not connected to the root", comp.id))

    if err and any(e.code in {"E_CYCLE", "E_PARENT_MISSING", "E_DUPLICATE_ID"} for e in err):
        return report  # geometry checks below assume a sane tree

    # geometry ----------------------------------------------------------------------------
    page_box = BBox(x=0, y=0, w=doc.page.width, h=doc.page.height)
    root = doc.require(doc.root_id) if doc.root_id in ids else None
    if root is not None and (abs(root.bbox.w - page_box.w) > tolerance_px or abs(root.bbox.h - page_box.h) > tolerance_px or abs(root.bbox.x) > tolerance_px or abs(root.bbox.y) > tolerance_px):
        warn.append(ValidationIssue("W_ROOT_BOX", "root box does not match page size", root.id))

    for comp in doc.components:
        if comp.id == doc.root_id:
            continue
        if intersection_area(comp.bbox, page_box) == 0.0:
            err.append(ValidationIssue("E_OUTSIDE_PAGE", "box lies completely outside the page", comp.id))
        elif not contains(page_box, comp.bbox, tolerance_px):
            warn.append(ValidationIssue("W_OUTSIDE_PAGE", "box extends past the page edge", comp.id))
        parent = by_id.get(comp.parent_id) if comp.parent_id else None
        if parent is not None and not contains(parent.bbox, comp.bbox, tolerance_px):
            warn.append(ValidationIssue("W_OVERFLOW_PARENT", f"box extends outside parent {parent.id!r}", comp.id))

        if comp.text and comp.type in _NO_TEXT_TYPES:
            warn.append(ValidationIssue("W_TEXT_ON_NON_TEXT", f"type {comp.type.value} should not carry text", comp.id))
        if comp.text_is_inferred and not comp.text:
            warn.append(ValidationIssue("W_INFERRED_FLAG_NO_TEXT", "text_is_inferred set but text is empty", comp.id))

    return report


def assert_valid(doc: DesignDocument) -> None:
    validate_document(doc).raise_if_invalid()
