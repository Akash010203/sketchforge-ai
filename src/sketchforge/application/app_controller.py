"""The application controller: the one object the UI (or a script) talks to.

Desktop UI -> AppController -> workflows / domain modules, all as direct in-process calls. The
controller holds no Qt types, so it runs identically under the GUI, the CLI and the tests.

Threading: ``*_async`` methods run on the task manager's worker threads and emit events when
done. Anything that mutates the open document runs on the caller's thread; long computations
work on a *copy* of the document and are applied back as one undoable step.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sketchforge.application.events import EventBus
from sketchforge.application.import_export import export_design
from sketchforge.application.project_manager import Project
from sketchforge.application.task_manager import Task, TaskManager, progress
from sketchforge.bootstrap import AppConfig, load_config
from sketchforge.design_ir.schema import Component, DesignDocument
from sketchforge.design_ir.serialization import document_hash, from_dict
from sketchforge.editor.design_commands import Command, ReplaceDocumentCommand
from sketchforge.editor.property_editing import make_edit
from sketchforge.editor.selection import hit_test
from sketchforge.evaluation.evaluator import EvaluationResult, evaluate_document
from sketchforge.evaluation.report import RepairReport
from sketchforge.exceptions import EditError, SketchForgeError
from sketchforge.integrations.provider_interface import ModelProvider
from sketchforge.orchestration.repair_workflow import run_repair
from sketchforge.orchestration.sketch_workflow import IMPORT_STEPS, run_sketch_workflow
from sketchforge.orchestration.workflow_state import RunStatus
from sketchforge.rendering.renderer import RenderedDesign, render_all
from sketchforge.repair.error_injection import Injection, inject
from sketchforge.utilities.paths import repo_root


class NoProjectError(SketchForgeError):
    """An operation needs an open project and there is none."""


class AppController:
    def __init__(self, config: AppConfig | None = None, tasks: TaskManager | None = None,
                 model_provider: ModelProvider | None = None) -> None:
        self.config = config or load_config()
        self.tasks = tasks or TaskManager()
        self.events = EventBus()
        # Optional and explicitly injected: remote assistance stays off unless the host has
        # configured and consented to a provider.
        self.model_provider = model_provider
        self._project: Project | None = None
        self._render_cache: tuple[int, RenderedDesign] | None = None
        self._lock = threading.RLock()  # serialises document mutations (GUI thread vs repair thread)

    # ------------------------------------------------------------------ state
    @property
    def project(self) -> Project:
        if self._project is None:
            raise NoProjectError("no project is open; import a sketch first")
        return self._project

    @property
    def has_project(self) -> bool:
        return self._project is not None

    @property
    def document(self) -> DesignDocument:
        return self.project.document

    def sample_sketches(self) -> list[Path]:
        folder = repo_root() / "assets" / "sample_sketches"
        return sorted(p for p in folder.glob("*.png")) if folder.is_dir() else []

    def _set_project(self, project: Project) -> None:
        self._project = project
        self._render_cache = None
        self.events.emit("project_opened", project=project)
        self.events.emit("document_changed", touched=set(), revision=project.stack.revision)

    def _changed(self, touched: set[str]) -> None:
        self._render_cache = None
        self.project.evaluation = None
        self.events.emit("document_changed", touched=touched, revision=self.project.stack.revision)

    # ------------------------------------------------------------------ import
    def import_sketch(self, path: str | Path, *, name: str | None = None,
                      task: Task | None = None) -> Project:
        """Load, analyse, build, validate and evaluate a sketch. Raises on failure."""
        def on_progress(step: str, index: int, total: int) -> None:
            text = f"{step} ({index + 1}/{total})"
            if task is not None:
                progress(task, text)
            self.events.emit("progress", text=text, fraction=index / total)

        state = run_sketch_workflow(path, config=self.config, steps=IMPORT_STEPS, name=name,
                                    on_progress=on_progress)
        if state.status is not RunStatus.SUCCEEDED:
            msg = f"import failed at '{state.failed_step}': {state.error}"
            self.events.emit("error", message=msg)
            raise SketchForgeError(msg)
        ctx = state.context
        project = Project.create(
            name or ctx["loaded"].name, ctx["document"], source=ctx["loaded"], vision=ctx["vision"],
            evaluation=ctx["evaluation"],
        )
        project.stack = ctx["stack"]
        project.saved_revision = project.stack.revision
        self._set_project(project)
        self.events.emit("evaluation_changed", evaluation=project.evaluation)
        return project

    def import_sketch_async(self, path: str | Path, *, name: str | None = None,
                            on_done: Callable[[Task], None] | None = None,
                            on_error: Callable[[Task], None] | None = None) -> Task:
        def work(task: Task) -> Project:
            return self.import_sketch(path, name=name, task=task)

        def failed(task: Task) -> None:
            self.events.emit("error", message=str(task.error))
            if on_error:
                on_error(task)

        return self.tasks.submit("import sketch", work, on_done=on_done, on_error=failed,
                                 on_progress=lambda t: self.events.emit("task_progress", task=t))

    def open_project(self, directory: str | Path) -> Project:
        project = Project.load(directory)
        self._set_project(project)
        return project

    def save_project(self, directory: str | Path | None = None) -> Path:
        project = self.project
        target = directory or project.path
        if target is None:
            raise SketchForgeError("choose a folder to save the project in")
        root = project.save(target)
        export_design(project.document, root / "renders", "design", project.last_report)
        self.events.emit("project_saved", path=root)
        return root

    def export(self, directory: str | Path) -> dict[str, Path]:
        return export_design(self.document, directory, "design", self.project.last_report)

    # ------------------------------------------------------------------ rendering
    def render(self) -> RenderedDesign:
        project = self.project
        key = project.stack.revision
        if self._render_cache is None or self._render_cache[0] != key:
            self._render_cache = (key, render_all(project.document))
        return self._render_cache[1]

    # ------------------------------------------------------------------ editing
    def execute(self, command: Command) -> None:
        with self._lock:
            project = self.project
            project.stack.execute(command)
            project.selection.prune(project.document)
        self._changed(command.touched_ids())

    def edit_property(self, component_id: str, prop: str, value: Any) -> None:
        self.execute(make_edit(self.document, component_id, prop, value))

    def move_component(self, component_id: str, dx: float, dy: float) -> None:
        from sketchforge.editor.design_commands import MoveCommand

        self.execute(MoveCommand(component_id, dx, dy))

    def resize_component(self, component_id: str, width: float, height: float) -> None:
        from sketchforge.design_ir.schema import BBox
        from sketchforge.editor.design_commands import SetBBoxCommand

        b = self.document.require(component_id).bbox
        self.execute(SetBBoxCommand(component_id, BBox(x=b.x, y=b.y, w=width, h=height)))

    def undo(self) -> str | None:
        with self._lock:
            stack = self.project.stack
            if not stack.can_undo:
                return None
            label = stack.undo_label()
            cmd = stack.undo()
            self.project.selection.prune(self.document)
        self._changed(cmd.touched_ids())
        return label

    def redo(self) -> str | None:
        with self._lock:
            stack = self.project.stack
            if not stack.can_redo:
                return None
            label = stack.redo_label()
            cmd = stack.redo()
        self._changed(cmd.touched_ids())
        return label

    def select(self, ids: list[str]) -> None:
        self.project.selection.set([i for i in ids if self.document.get(i) is not None])
        self.events.emit("selection_changed", ids=self.project.selection.ids)

    def select_at(self, x: float, y: float) -> Component | None:
        hit = hit_test(self.document, x, y)
        self.select([hit.id] if hit else [])
        return hit

    # ------------------------------------------------------------------ evaluation & repair
    def evaluate(self) -> EvaluationResult:
        project = self.project
        project.evaluation = evaluate_document(project.document, self.config.constraints)
        self.events.emit("evaluation_changed", evaluation=project.evaluation)
        return project.evaluation

    def inject_error(self, kind: str) -> Injection:
        with self._lock:
            record = inject(self.document, kind, self.project.stack, self.config.constraints)
        self._changed(set(record.component_ids))
        self.evaluate()
        return record

    def run_repair(self, *, injection: Injection | None = None) -> RepairReport:
        """Run the repair loop synchronously on a copy and apply the result as one undoable step."""
        project = self.project
        copy = from_dict(project.document.snapshot())
        revision = project.stack.revision
        report = run_repair(
            copy, constraints=self.config.constraints, policy=self.config.regression,
            limits=self.config.workflow, injection=injection.to_dict() if injection else None,
            model_provider=self.model_provider,
            on_event=lambda name, data: self.events.emit("repair_event", name=name, **data),
        )
        self._apply_repair(report, copy, revision)
        return report

    def run_repair_async(self, *, injection: Injection | None = None,
                         on_done: Callable[[Task], None] | None = None) -> Task:
        project = self.project
        copy = from_dict(project.document.snapshot())
        revision = project.stack.revision
        self.events.emit("repair_started")

        def work(task: Task) -> RepairReport:
            report = run_repair(
                copy, constraints=self.config.constraints, policy=self.config.regression,
                limits=self.config.workflow, cancelled=lambda: task.cancelled,
                model_provider=self.model_provider,
                injection=injection.to_dict() if injection else None,
                on_event=lambda name, data: (
                    progress(task, f"{name}: {data.get('issue', data.get('decision', ''))}"),
                    self.events.emit("repair_event", name=name, **data)),
            )
            self._apply_repair(report, copy, revision)
            return report

        return self.tasks.submit("repair", work, on_done=on_done,
                                 on_error=lambda t: self.events.emit("error", message=str(t.error)))

    def _apply_repair(self, report: RepairReport, repaired: DesignDocument, base_revision: int) -> None:
        project = self.project
        with self._lock:
            if project.stack.revision != base_revision:
                msg = "the design changed while the repair was running; run it again"
                self.events.emit("error", message=msg)
                raise EditError(msg)
            project.last_report = report
            if report.accepted:
                project.stack.execute(ReplaceDocumentCommand(
                    repaired.snapshot(), f"automatic repair ({len(report.accepted)} patch(es))"))
                project.selection.prune(project.document)
            if report.accepted and document_hash(project.document) != report.hash_after:
                raise EditError("internal error: the applied repair does not match the verified result")
        self._changed({cid for r in report.accepted for cid in r.patch.component_ids})
        project.evaluation = report.final
        self.events.emit("repair_finished", report=report)
        self.events.emit("evaluation_changed", evaluation=report.final)

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        self.tasks.shutdown(wait=True)


def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    t0 = time.perf_counter()
    return fn(), (time.perf_counter() - t0) * 1000
