"""Document construction and tree operations on a :class:`DesignDocument`.

All structural changes go through these helpers so the document's lookup index stays correct.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from sketchforge.design_ir.geometry import translate
from sketchforge.design_ir.schema import (
    BBox,
    Component,
    ComponentType,
    DesignDocument,
    DocumentMetadata,
    Page,
    Style,
    Viewport,
)
from sketchforge.exceptions import SketchForgeError

ROOT_ID = "page"


def new_document(
    name: str,
    width: float,
    height: float,
    *,
    document_id: str = "doc",
    device: str = "desktop",
    background: str = "#ffffff",
    metadata: DocumentMetadata | None = None,
) -> DesignDocument:
    """Create a document containing only the root ``page`` component."""
    page = Page(
        width=width,
        height=height,
        background=background,
        viewport=Viewport(width=int(round(width)), height=int(round(height)), device=device),
    )
    root = Component(
        id=ROOT_ID,
        type=ComponentType.PAGE,
        name=name,
        parent_id=None,
        bbox=BBox(x=0, y=0, w=width, h=height),
        style=Style(fill=background),
    )
    return DesignDocument(
        document_id=document_id,
        name=name,
        page=page,
        root_id=ROOT_ID,
        components=[root],
        metadata=metadata or DocumentMetadata(),
    )


def make_component_id(doc: DesignDocument, prefix: str) -> str:
    """Deterministic unique id: ``<prefix>-<n>`` with the smallest unused n."""
    base = re.sub(r"[^a-z0-9_-]", "-", prefix.lower()).strip("-") or "c"
    if not base[0].isalpha():
        base = "c-" + base
    used = {c.id for c in doc.components}
    n = 1
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


def add_component(doc: DesignDocument, component: Component, *, index: int | None = None) -> None:
    if doc.get(component.id) is not None:
        raise SketchForgeError(f"component id already exists: {component.id}")
    if component.parent_id is None or doc.get(component.parent_id) is None:
        raise SketchForgeError(f"parent does not exist: {component.parent_id!r}")
    if index is None:
        doc.components.append(component)
    else:
        doc.components.insert(index, component)
    doc.invalidate_index()


def descendants_of(doc: DesignDocument, component_id: str) -> list[Component]:
    """All descendants in pre-order (parents before children), excluding the component itself."""
    out: list[Component] = []
    stack = list(reversed(doc.children_ids(component_id)))
    while stack:
        cid = stack.pop()
        out.append(doc.require(cid))
        stack.extend(reversed(doc.children_ids(cid)))
    return out


def subtree_of(doc: DesignDocument, component_id: str) -> list[Component]:
    return [doc.require(component_id), *descendants_of(doc, component_id)]


def preorder(doc: DesignDocument) -> Iterator[Component]:
    yield doc.root
    yield from descendants_of(doc, doc.root_id)


def ancestors_of(doc: DesignDocument, component_id: str) -> list[Component]:
    """Parent first, root last."""
    out: list[Component] = []
    seen: set[str] = set()
    current = doc.require(component_id)
    while current.parent_id is not None and current.parent_id not in seen:
        seen.add(current.parent_id)
        parent = doc.require(current.parent_id)
        out.append(parent)
        current = parent
    return out


def depth_of(doc: DesignDocument, component_id: str) -> int:
    return len(ancestors_of(doc, component_id))


def remove_subtree(doc: DesignDocument, component_id: str) -> list[tuple[int, Component]]:
    """Remove a component and its descendants.

    Returns ``(original list index, component)`` pairs in ascending index order so an undo can
    re-insert them exactly where they were.
    """
    if component_id == doc.root_id:
        raise SketchForgeError("the root page cannot be removed")
    doomed = {c.id for c in subtree_of(doc, component_id)}
    removed = [(i, c) for i, c in enumerate(doc.components) if c.id in doomed]
    doc.components = [c for c in doc.components if c.id not in doomed]
    doc.invalidate_index()
    return removed


def restore_components(doc: DesignDocument, removed: list[tuple[int, Component]]) -> None:
    """Inverse of :func:`remove_subtree`."""
    comps = list(doc.components)
    for index, comp in removed:  # ascending order keeps indices valid
        comps.insert(index, comp)
    doc.components = comps
    doc.invalidate_index()


def move_subtree(doc: DesignDocument, component_id: str, dx: float, dy: float) -> None:
    """Translate a component and everything below it by (dx, dy)."""
    for comp in subtree_of(doc, component_id):
        comp.bbox = translate(comp.bbox, dx, dy)


def reparent(doc: DesignDocument, component_id: str, new_parent_id: str) -> None:
    if component_id == doc.root_id:
        raise SketchForgeError("the root page cannot be reparented")
    if doc.get(new_parent_id) is None:
        raise SketchForgeError(f"unknown parent {new_parent_id!r}")
    if new_parent_id == component_id or new_parent_id in {
        c.id for c in descendants_of(doc, component_id)
    }:
        raise SketchForgeError("cannot reparent a component under itself or its descendants")
    doc.require(component_id).parent_id = new_parent_id
    doc.invalidate_index()
