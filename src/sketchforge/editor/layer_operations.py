"""Layer ordering helpers."""

from __future__ import annotations

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.editor.design_commands import CompositeCommand, SetZIndexCommand
from sketchforge.exceptions import EditError


def reorder(doc: DesignDocument, component_id: str, direction: str) -> CompositeCommand:
    """Move a component forward/backward among its siblings (``front``/``back``/``up``/``down``).

    Siblings are renumbered 0..n-1 in one undoable step so z-indices stay dense and unambiguous.
    """
    comp = doc.require(component_id)
    if comp.parent_id is None:
        raise EditError("the page has no siblings to reorder")
    order = doc.children_ids(comp.parent_id)
    i = order.index(component_id)
    order.pop(i)
    j = {"front": len(order), "back": 0, "up": min(i + 1, len(order)), "down": max(i - 1, 0)}.get(direction)
    if j is None:
        raise EditError("direction must be one of front, back, up, down")
    order.insert(j, component_id)
    cmds = [SetZIndexCommand(cid, n) for n, cid in enumerate(order) if doc.require(cid).z_index != n]
    return CompositeCommand(cmds, f"send {component_id} {direction}")
