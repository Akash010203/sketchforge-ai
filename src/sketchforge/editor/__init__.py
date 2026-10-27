"""Editing: undoable commands, undo/redo, selection and property editing on the Design IR."""

from sketchforge.editor.design_commands import (
    AddComponentCommand,
    Command,
    CompositeCommand,
    MoveCommand,
    RemoveComponentCommand,
    RenameCommand,
    ReparentCommand,
    ReplaceDocumentCommand,
    SetBBoxCommand,
    SetLayoutCommand,
    SetStyleCommand,
    SetTextCommand,
    SetTypographyCommand,
    SetVisibleCommand,
    SetZIndexCommand,
)
from sketchforge.editor.property_editing import make_edit
from sketchforge.editor.selection import Selection, hit_test
from sketchforge.editor.undo_redo import UndoStack

__all__ = [
    "AddComponentCommand", "Command", "CompositeCommand", "MoveCommand", "RemoveComponentCommand",
    "RenameCommand", "ReparentCommand", "ReplaceDocumentCommand", "Selection", "SetBBoxCommand", "SetLayoutCommand",
    "SetStyleCommand", "SetTextCommand", "SetTypographyCommand", "SetVisibleCommand",
    "SetZIndexCommand", "UndoStack", "hit_test", "make_edit",
]
