"""Undoable edits to a Design IR document.

Every change to a document, whether it comes from the properties panel, a drag on the canvas or an
automatic repair patch, is a :class:`Command`. A command captures the exact prior state when it
runs, so ``undo`` restores it byte-for-byte (no floating point drift) and ``do`` can be replayed
for redo. Commands validate through the IR models, so an invalid edit raises
:class:`EditError` and leaves the document untouched.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from sketchforge.design_ir.document import (
    add_component,
    remove_subtree,
    reparent,
    restore_components,
    subtree_of,
)
from sketchforge.design_ir.geometry import translate
from sketchforge.design_ir.schema import (
    BBox,
    Component,
    ComponentType,
    DesignDocument,
    LayoutSpec,
    Style,
    Typography,
)
from sketchforge.exceptions import EditError

_TEXT_TYPES = {
    ComponentType.TEXT, ComponentType.HEADING, ComponentType.BUTTON, ComponentType.INPUT,
}


def _updated(model: BaseModel, changes: dict[str, Any]) -> Any:
    """A validated copy of ``model`` with ``changes`` applied (pydantic's model_copy skips
    validation, so go through model_validate)."""
    try:
        return type(model).model_validate({**model.model_dump(), **changes})
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"])
        raise EditError(f"invalid value for {field}: {first['msg']}") from exc


class Command(ABC):
    """Base class. Subclasses implement :meth:`do` and :meth:`undo`."""

    description: str = "edit"
    respect_locks: bool = True

    @abstractmethod
    def do(self, doc: DesignDocument) -> None: ...

    @abstractmethod
    def undo(self, doc: DesignDocument) -> None: ...

    def touched_ids(self) -> set[str]:
        return set()

    # ------------------------------------------------------------------ helpers
    def _component(self, doc: DesignDocument, component_id: str, field: str | None = None) -> Component:
        comp = doc.get(component_id)
        if comp is None:
            raise EditError(f"no component {component_id!r}")
        if self.respect_locks and field is not None:
            if comp.locked:
                raise EditError(f"{component_id} is locked")
            if field not in comp.editable:
                raise EditError(f"{component_id} does not allow editing '{field}'")
        return comp


class SetTextCommand(Command):
    def __init__(self, component_id: str, text: str | None, *, mark_inferred: bool = False) -> None:
        self.component_id, self.text, self.mark_inferred = component_id, text, mark_inferred
        self.description = f"set text of {component_id}"
        self._before: tuple[str | None, bool] | None = None

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id, "text")
        if comp.type not in _TEXT_TYPES and comp.type is not ComponentType.CHECKBOX and comp.type is not ComponentType.RADIO:
            raise EditError(f"{comp.type.value} components do not carry text")
        if self.text is not None and len(self.text) > 2000:
            raise EditError("text is longer than 2000 characters")
        self._before = (comp.text, comp.text_is_inferred)
        comp.text = self.text
        comp.text_is_inferred = self.mark_inferred and bool(self.text)

    def undo(self, doc: DesignDocument) -> None:
        assert self._before is not None
        comp = doc.require(self.component_id)
        comp.text, comp.text_is_inferred = self._before

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class SetStyleCommand(Command):
    def __init__(self, component_id: str, **changes: Any) -> None:
        self.component_id, self.changes = component_id, changes
        self.description = f"set style of {component_id}: {', '.join(f'{k}={v}' for k, v in changes.items())}"
        self._before: Style | None = None

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id, "style")
        new = _updated(comp.style, self.changes)
        self._before = comp.style
        comp.style = new

    def undo(self, doc: DesignDocument) -> None:
        assert self._before is not None
        doc.require(self.component_id).style = self._before

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class SetTypographyCommand(Command):
    def __init__(self, component_id: str, **changes: Any) -> None:
        self.component_id, self.changes = component_id, changes
        self.description = f"set typography of {component_id}: {', '.join(f'{k}={v}' for k, v in changes.items())}"
        self._before: Typography | None = None
        self._had: bool = False

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id, "typography")
        base = comp.typography or Typography()
        new = _updated(base, self.changes)
        self._had, self._before = comp.typography is not None, comp.typography
        comp.typography = new

    def undo(self, doc: DesignDocument) -> None:
        doc.require(self.component_id).typography = self._before if self._had else None

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class SetBBoxCommand(Command):
    """Set a component's box. Children are *not* moved (use :class:`MoveCommand` for that)."""

    def __init__(self, component_id: str, bbox: BBox, *, reason: str | None = None) -> None:
        self.component_id, self.bbox = component_id, bbox
        self.description = reason or f"set box of {component_id}"
        self._before: BBox | None = None

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id, "bbox")
        if comp.id == doc.root_id:
            raise EditError("the page box follows the page size and cannot be edited directly")
        self._before = comp.bbox
        comp.bbox = self.bbox

    def undo(self, doc: DesignDocument) -> None:
        assert self._before is not None
        doc.require(self.component_id).bbox = self._before

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class MoveCommand(Command):
    """Translate a component and all of its descendants by (dx, dy)."""

    def __init__(self, component_id: str, dx: float, dy: float, *, reason: str | None = None) -> None:
        self.component_id, self.dx, self.dy = component_id, dx, dy
        self.description = reason or f"move {component_id} by ({dx:.1f}, {dy:.1f})"
        self._before: dict[str, BBox] = {}

    def do(self, doc: DesignDocument) -> None:
        root = self._component(doc, self.component_id, "bbox")
        if root.id == doc.root_id:
            raise EditError("the page cannot be moved")
        members = subtree_of(doc, self.component_id)
        if self.respect_locks:
            for member in members:
                if member.locked:
                    raise EditError(f"{member.id} is locked")
        new = {m.id: translate(m.bbox, self.dx, self.dy) for m in members}  # validates first
        self._before = {m.id: m.bbox for m in members}
        for m in members:
            m.bbox = new[m.id]

    def undo(self, doc: DesignDocument) -> None:
        for cid, box in self._before.items():
            doc.require(cid).bbox = box

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class SetLayoutCommand(Command):
    def __init__(self, component_id: str, **changes: Any) -> None:
        self.component_id, self.changes = component_id, changes
        self.description = f"set layout of {component_id}"
        self._before: LayoutSpec | None = None

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id, "style")
        new = _updated(comp.layout or LayoutSpec(), {**self.changes, "inferred": False})
        self._before = comp.layout
        comp.layout = new

    def undo(self, doc: DesignDocument) -> None:
        doc.require(self.component_id).layout = self._before

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class RenameCommand(Command):
    def __init__(self, component_id: str, name: str) -> None:
        self.component_id, self.name = component_id, name
        self.description = f"rename {component_id}"
        self._before: str | None = None

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id)
        if len(self.name) > 120:
            raise EditError("name is longer than 120 characters")
        self._before = comp.name
        comp.name = self.name

    def undo(self, doc: DesignDocument) -> None:
        doc.require(self.component_id).name = self._before

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class SetVisibleCommand(Command):
    def __init__(self, component_id: str, visible: bool) -> None:
        self.component_id, self.visible = component_id, visible
        self.description = f"{'show' if visible else 'hide'} {component_id}"
        self._before = True

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id)
        if comp.id == doc.root_id:
            raise EditError("the page cannot be hidden")
        self._before = comp.visible
        comp.visible = self.visible

    def undo(self, doc: DesignDocument) -> None:
        doc.require(self.component_id).visible = self._before

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class AddComponentCommand(Command):
    def __init__(self, component: Component, *, index: int | None = None) -> None:
        self.component, self.index = component, index
        self.description = f"add {component.type.value} {component.id}"

    def do(self, doc: DesignDocument) -> None:
        parent = doc.get(self.component.parent_id or "")
        if parent is not None and self.respect_locks and parent.locked:
            raise EditError(f"{parent.id} is locked")
        try:
            add_component(doc, self.component.model_copy(deep=True), index=self.index)
        except Exception as exc:
            raise EditError(str(exc)) from exc

    def undo(self, doc: DesignDocument) -> None:
        remove_subtree(doc, self.component.id)

    def touched_ids(self) -> set[str]:
        return {self.component.id}


class RemoveComponentCommand(Command):
    def __init__(self, component_id: str) -> None:
        self.component_id = component_id
        self.description = f"delete {component_id}"
        self._removed: list[tuple[int, Component]] = []

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id)
        if comp.id == doc.root_id:
            raise EditError("the page cannot be deleted")
        if self.respect_locks and any(m.locked for m in subtree_of(doc, comp.id)):
            raise EditError(f"{comp.id} or one of its children is locked")
        self._removed = remove_subtree(doc, self.component_id)

    def undo(self, doc: DesignDocument) -> None:
        restore_components(doc, self._removed)

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class ReparentCommand(Command):
    def __init__(self, component_id: str, new_parent_id: str) -> None:
        self.component_id, self.new_parent_id = component_id, new_parent_id
        self.description = f"move {component_id} into {new_parent_id}"
        self._before: str | None = None

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id, "bbox")
        self._before = comp.parent_id
        try:
            reparent(doc, self.component_id, self.new_parent_id)
        except Exception as exc:
            raise EditError(str(exc)) from exc

    def undo(self, doc: DesignDocument) -> None:
        assert self._before is not None
        doc.require(self.component_id).parent_id = self._before
        doc.invalidate_index()

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class SetZIndexCommand(Command):
    def __init__(self, component_id: str, z_index: int) -> None:
        self.component_id, self.z_index = component_id, z_index
        self.description = f"set layer order of {component_id} to {z_index}"
        self._before = 0

    def do(self, doc: DesignDocument) -> None:
        comp = self._component(doc, self.component_id)
        self._before = comp.z_index
        comp.z_index = self.z_index
        doc.invalidate_index()

    def undo(self, doc: DesignDocument) -> None:
        doc.require(self.component_id).z_index = self._before
        doc.invalidate_index()

    def touched_ids(self) -> set[str]:
        return {self.component_id}


class CompositeCommand(Command):
    """Several commands that succeed or fail together and undo as one step."""

    def __init__(self, commands: list[Command], description: str) -> None:
        self.commands, self.description = list(commands), description

    def do(self, doc: DesignDocument) -> None:
        done: list[Command] = []
        try:
            for cmd in self.commands:
                cmd.respect_locks = self.respect_locks
                cmd.do(doc)
                done.append(cmd)
        except Exception:
            for cmd in reversed(done):
                cmd.undo(doc)
            raise

    def undo(self, doc: DesignDocument) -> None:
        for cmd in reversed(self.commands):
            cmd.undo(doc)

    def touched_ids(self) -> set[str]:
        out: set[str] = set()
        for cmd in self.commands:
            out |= cmd.touched_ids()
        return out


class ReplaceDocumentCommand(Command):
    """Swap the whole document content for ``after`` in one undoable step.

    Used to apply the result of an automatic repair that ran on a copy in the background.
    """

    def __init__(self, after: dict[str, Any], description: str = "automatic repair") -> None:
        self.after, self.description = after, description
        self._before: dict[str, Any] | None = None

    def do(self, doc: DesignDocument) -> None:
        self._before = doc.snapshot()
        doc.restore(self.after)

    def undo(self, doc: DesignDocument) -> None:
        assert self._before is not None
        doc.restore(self._before)

    def touched_ids(self) -> set[str]:
        return set()
