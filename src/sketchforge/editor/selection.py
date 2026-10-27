"""Selection state and hit-testing on the Design IR."""

from __future__ import annotations

from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.schema import BBox, Component, DesignDocument


def hit_test(doc: DesignDocument, x: float, y: float, *, include_root: bool = False) -> Component | None:
    """The deepest, last-drawn visible component under the point (design coordinates)."""
    hit: Component | None = None
    hidden: set[str] = set()
    for comp in preorder(doc):  # pre-order == paint order, so later hits are on top
        if not comp.visible or comp.parent_id in hidden:
            hidden.add(comp.id)
            continue
        if comp.id == doc.root_id and not include_root:
            continue
        b = comp.bbox
        if b.x <= x <= b.x2 and b.y <= y <= b.y2:
            hit = comp
    return hit


def components_in_rect(doc: DesignDocument, rect: BBox) -> list[Component]:
    out = []
    for comp in preorder(doc):
        if comp.id == doc.root_id or not comp.visible:
            continue
        b = comp.bbox
        if b.x >= rect.x and b.y >= rect.y and b.x2 <= rect.x2 and b.y2 <= rect.y2:
            out.append(comp)
    return out


class Selection:
    def __init__(self) -> None:
        self._ids: list[str] = []

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    @property
    def primary(self) -> str | None:
        return self._ids[-1] if self._ids else None

    def set(self, ids: list[str]) -> None:
        self._ids = list(dict.fromkeys(ids))

    def toggle(self, component_id: str) -> None:
        if component_id in self._ids:
            self._ids.remove(component_id)
        else:
            self._ids.append(component_id)

    def clear(self) -> None:
        self._ids.clear()

    def prune(self, doc: DesignDocument) -> None:
        """Drop ids that no longer exist (after a delete or undo)."""
        self._ids = [i for i in self._ids if doc.get(i) is not None]
