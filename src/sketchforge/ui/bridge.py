"""Turns controller events (emitted on any thread) into Qt signals delivered on the GUI thread."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from sketchforge.application.app_controller import AppController


class ControllerBridge(QObject):
    project_opened = Signal()
    document_changed = Signal(object, int)  # touched ids, revision
    selection_changed = Signal(object)  # tuple of ids
    evaluation_changed = Signal(object)
    repair_started = Signal()
    repair_finished = Signal(object)
    repair_event = Signal(str, object)
    progress = Signal(str)
    error = Signal(str)
    project_saved = Signal(object)

    def __init__(self, controller: AppController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        ev = controller.events
        self._unsubscribe = [
            ev.subscribe("project_opened", lambda **_: self.project_opened.emit()),
            ev.subscribe("document_changed", lambda touched, revision, **_: self.document_changed.emit(touched, revision)),
            ev.subscribe("selection_changed", lambda ids, **_: self.selection_changed.emit(ids)),
            ev.subscribe("evaluation_changed", lambda evaluation, **_: self.evaluation_changed.emit(evaluation)),
            ev.subscribe("repair_started", lambda **_: self.repair_started.emit()),
            ev.subscribe("repair_finished", lambda report, **_: self.repair_finished.emit(report)),
            ev.subscribe("repair_event", self._repair_event),
            ev.subscribe("progress", lambda text, **_: self.progress.emit(text)),
            ev.subscribe("task_progress", lambda task, **_: self.progress.emit(getattr(task, "progress", "") or "")),
            ev.subscribe("error", lambda message, **_: self.error.emit(message)),
            ev.subscribe("project_saved", lambda path, **_: self.project_saved.emit(path)),
        ]

    def _repair_event(self, name: str, **data: Any) -> None:
        self.repair_event.emit(name, data)

    def detach(self) -> None:
        for off in self._unsubscribe:
            off()
        self._unsubscribe.clear()
