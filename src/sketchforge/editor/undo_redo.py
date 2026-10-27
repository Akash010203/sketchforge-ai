"""Undo/redo stack over a Design IR document."""

from __future__ import annotations

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.editor.change_history import ChangeHistory
from sketchforge.editor.design_commands import Command
from sketchforge.exceptions import EditError


class UndoStack:
    """Executes commands against ``document`` and lets the user step back and forward.

    A command that raises leaves the document untouched and is not recorded.
    """

    def __init__(self, document: DesignDocument, limit: int = 500) -> None:
        self.document = document
        self.limit = limit
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self.history = ChangeHistory()
        self.revision = 0  # increments on every successful change, for dirty-tracking and caches

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def execute(self, command: Command) -> None:
        command.do(self.document)  # raises EditError/other without recording
        self._undo.append(command)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()
        self.revision += 1
        self.history.add("do", command.description, command.touched_ids())

    def undo(self) -> Command:
        if not self._undo:
            raise EditError("nothing to undo")
        command = self._undo.pop()
        command.undo(self.document)
        self._redo.append(command)
        self.revision += 1
        self.history.add("undo", command.description, command.touched_ids())
        return command

    def redo(self) -> Command:
        if not self._redo:
            raise EditError("nothing to redo")
        command = self._redo.pop()
        command.do(self.document)
        self._undo.append(command)
        self.revision += 1
        self.history.add("redo", command.description, command.touched_ids())
        return command

    def undo_label(self) -> str | None:
        return self._undo[-1].description if self._undo else None

    def redo_label(self) -> str | None:
        return self._redo[-1].description if self._redo else None

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
