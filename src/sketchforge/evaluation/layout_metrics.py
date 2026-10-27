"""Structural layout checks on a Design IR document.

All thresholds come from :class:`LayoutConstraints`. Every check is a pure function of the
document, so the same document always yields the same issues.
"""

from __future__ import annotations

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.geometry import intersection_area
from sketchforge.design_ir.schema import CONTAINER_TYPES, BBox, ComponentType, DesignDocument
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.issues import Issue
from sketchforge.layout.grouping import (
    alignable_siblings,
    find_misalignments,
    repeated_groups,
)

_INTERACTIVE_LARGE = {ComponentType.BUTTON, ComponentType.INPUT}
_INTERACTIVE_SMALL = {ComponentType.CHECKBOX, ComponentType.RADIO}


def overshoot(inner: BBox, outer: BBox) -> dict[str, float]:
    """How far ``inner`` extends past each side of ``outer`` (only positive values)."""
    sides = {
        "left": outer.x - inner.x, "top": outer.y - inner.y,
        "right": inner.x2 - outer.x2, "bottom": inner.y2 - outer.y2,
    }
    return {k: v for k, v in sides.items() if v > 0}


def check_containment(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    found: list[Issue] = []
    page = BBox(x=0, y=0, w=doc.page.width, h=doc.page.height)
    for comp in preorder(doc):
        if comp.id == doc.root_id or not comp.visible:
            continue
        parent = doc.get(comp.parent_id) if comp.parent_id else None
        if parent is not None and parent.id != doc.root_id:
            over = {k: v for k, v in overshoot(comp.bbox, parent.bbox).items() if v > c.containment_tolerance_px}
            if over:
                worst = max(over, key=over.get)
                found.append(Issue(
                    I.OVERFLOW_PARENT, (comp.id,),
                    f"{comp.id} extends {over[worst]:.1f}px past the {worst} edge of {parent.id}",
                    max(over.values()), worst,
                    {"parent": parent.id, **{f"over_{k}": round(v, 3) for k, v in over.items()}},
                ))
        over_page = {k: v for k, v in overshoot(comp.bbox, page).items() if v > c.page_margin_tolerance_px}
        if over_page:
            worst = max(over_page, key=over_page.get)
            found.append(Issue(
                I.OVERFLOW_PAGE, (comp.id,),
                f"{comp.id} extends {over_page[worst]:.1f}px past the {worst} edge of the page",
                max(over_page.values()), worst,
                {f"over_{k}": round(v, 3) for k, v in over_page.items()},
            ))
    return found


def check_overlap(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    found: list[Issue] = []
    for parent in preorder(doc):
        if parent.type not in CONTAINER_TYPES:
            continue
        kids = alignable_siblings(doc, parent.id)
        for i, a in enumerate(kids):
            for b in kids[i + 1 :]:
                inter = intersection_area(a.bbox, b.bbox)
                if inter <= 0:
                    continue
                ratio = inter / min(a.bbox.area, b.bbox.area)
                if ratio > c.overlap_tolerance_ratio:
                    pair = tuple(sorted((a.id, b.id)))
                    found.append(Issue(
                        I.OVERLAP, pair,
                        f"{pair[0]} and {pair[1]} overlap by {ratio:.0%} of the smaller one",
                        ratio, "", {"intersection_px2": round(inter, 1)},
                    ))
    return found


def check_alignment(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    found: list[Issue] = []
    for parent in preorder(doc):
        if parent.type not in CONTAINER_TYPES:
            continue
        for m in find_misalignments(doc, parent.id, c.align_snap_radius_px, c.align_tolerance_px):
            found.append(Issue(
                I.MISALIGNED, (m.component_id,),
                f"{m.component_id} {m.edge} edge is {m.residual:.1f}px off its group "
                f"({', '.join(m.partners)})",
                m.residual, m.edge,
                {"edge": m.edge, "current": round(m.current, 3), "target": round(m.target, 3),
                 "parent": m.parent_id},
            ))
    return found


def check_spacing(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    found: list[Issue] = []
    for parent in preorder(doc):
        if parent.type not in CONTAINER_TYPES:
            continue
        for g in repeated_groups(doc, parent.id):
            spread = g.spread(doc)
            if spread > c.spacing_tolerance_px:
                pitches = g.pitches(doc)
                found.append(Issue(
                    I.UNEVEN_SPACING, g.member_ids,
                    f"{len(g.member_ids)} repeated items have pitches from {min(pitches):.1f} "
                    f"to {max(pitches):.1f}px",
                    spread, g.axis,
                    {"axis": g.axis, "min_pitch": round(min(pitches), 3), "max_pitch": round(max(pitches), 3)},
                ))
    return found


def check_sizes(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    found: list[Issue] = []
    for comp in doc.components:
        if not comp.visible:
            continue
        b = comp.bbox
        if comp.type in _INTERACTIVE_LARGE and b.h < c.min_touch_size_px:
            found.append(Issue(
                I.TOUCH_TARGET_SMALL, (comp.id,),
                f"{comp.id} is {b.h:.0f}px tall; controls should be at least {c.min_touch_size_px:.0f}px",
                c.min_touch_size_px - b.h, "height", {"size": round(b.h, 3), "minimum": c.min_touch_size_px},
            ))
        if comp.type in _INTERACTIVE_SMALL and min(b.w, b.h) < c.min_control_size_px:
            found.append(Issue(
                I.TOUCH_TARGET_SMALL, (comp.id,),
                f"{comp.id} is {min(b.w, b.h):.0f}px across; minimum is {c.min_control_size_px:.0f}px",
                c.min_control_size_px - min(b.w, b.h), "size",
                {"size": round(min(b.w, b.h), 3), "minimum": c.min_control_size_px},
            ))
    return found


def detect_layout_issues(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    return [
        *check_containment(doc, c), *check_overlap(doc, c), *check_alignment(doc, c),
        *check_spacing(doc, c), *check_sizes(doc, c),
    ]
