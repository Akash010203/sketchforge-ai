"""Main window: component tree and sketch on the left, canvas in the middle, inspector on the right."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QDrag, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sketchforge import __version__
from sketchforge.application.app_controller import AppController
from sketchforge.assist.edit_plan import PlanCommand, validate_plan
from sketchforge.assist.local_parser import parse_instruction
from sketchforge.assist.model_planner import plan_with_model
from sketchforge.domain.component_types import ComponentType
from sketchforge.exceptions import SketchForgeError
from sketchforge.ui.bridge import ControllerBridge
from sketchforge.ui.component_tree import ComponentTree
from sketchforge.ui.correction_panel import CorrectionPanel
from sketchforge.ui.dataset_panel import DatasetPanel
from sketchforge.ui.design_canvas import DesignCanvas
from sketchforge.ui.generation_panel import GenerationPanel
from sketchforge.ui.layer_panel import LayerPanel
from sketchforge.ui.preview_panel import PreviewPanel
from sketchforge.ui.properties_panel import PropertiesPanel
from sketchforge.ui.sketch_import_view import SketchImportView
from sketchforge.ui.settings_dialog import SettingsDialog
from sketchforge.ui.task_progress import TaskProgress
from sketchforge.ui.training_panel import TrainingPanel
from sketchforge.ui.workspace import WorkspaceState

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)"


class CanvasToolButton(QPushButton):
    """A palette item can be clicked to draw or dragged directly onto the canvas."""

    def __init__(self, label: str, kind: ComponentType, parent=None) -> None:
        super().__init__(label, parent)
        self.setObjectName("paletteTool")
        self.kind = kind
        self._press_pos = None
        self.setCheckable(True)
        self.setToolTip(f"Click, then draw {label}, or drag it onto the canvas")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength() >= 8):
            from PySide6.QtCore import QMimeData
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData("application/x-sketchforge-component", QByteArray(self.kind.value.encode()))
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            self._press_pos = None
            return
        super().mouseMoveEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self.bridge = ControllerBridge(controller, self)
        self.resize(1480, 900)

        # -- workspace state (tab indices, fit-pending, …) --
        self.workspace = WorkspaceState()

        # -- panels --
        self.canvas = DesignCanvas(controller)
        self.tree = ComponentTree(controller)
        self.sketch_view = SketchImportView(controller)
        self.layer_panel = LayerPanel(controller)
        self.properties = PropertiesPanel(controller)
        self.correction = CorrectionPanel(controller)
        self.preview = PreviewPanel(controller)
        self.training = TrainingPanel(controller)
        self.datasets = DatasetPanel(controller)
        self.progress = TaskProgress()
        self.generator = GenerationPanel(self, controller=controller)
        self.setStyleSheet(_studio_stylesheet())

        # -- left tab widget --
        left = QTabWidget()
        left.addTab(self.generator, "Create")
        left.addTab(self.tree, "Components")
        left.addTab(self.sketch_view, "Sketch")
        left.addTab(self.layer_panel, "Layers")
        left.addTab(self.datasets, "Datasets")

        # -- right tab widget --
        right = QTabWidget()
        right.addTab(self.preview, "Preview")
        right.addTab(self.properties, "Properties")
        right.addTab(self.correction, "Measure && repair")
        right.addTab(self.training, "Training")
        left.setCurrentWidget(self.generator)
        right.setCurrentWidget(self.properties)

        self.left_tabs, self.right_tabs = left, right

        # Persist tab changes in workspace state
        left.currentChanged.connect(lambda _: self.workspace.sync_tabs(left, right))
        right.currentChanged.connect(lambda _: self.workspace.sync_tabs(left, right))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        for w in (left, self.canvas, right):
            splitter.addWidget(w)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 760, 420])
        # A local, validated natural-language edit entry point. The SVG canvas remains the
        # interactive design surface; this bar translates requests into undoable IR commands.
        self.edit_prompt = QLineEdit()
        self.edit_prompt.setObjectName("naturalLanguageEditPrompt")
        self.edit_prompt.setPlaceholderText("Try “make the primary button blue” or “move the title down 12 px”…")
        self.edit_prompt.setAccessibleName("Natural language design edit")
        self.edit_prompt.returnPressed.connect(self.apply_prompt)
        self.apply_prompt_button = QPushButton("Apply edit")
        self.apply_prompt_button.clicked.connect(self.apply_prompt)
        prompt_row = QHBoxLayout()
        prompt_label = QLabel("✦  ASK SKETCHFORGE")
        prompt_label.setObjectName("sectionEyebrow")
        prompt_row.addWidget(prompt_label)
        prompt_row.addWidget(self.edit_prompt, 1)
        prompt_row.addWidget(self.apply_prompt_button)
        palette_row = QHBoxLayout()
        insert_label = QLabel("INSERT")
        insert_label.setObjectName("sectionEyebrow")
        palette_row.addWidget(insert_label)
        self._palette_buttons = []
        for label, kind in (("Button", ComponentType.BUTTON), ("Input", ComponentType.INPUT),
                             ("Text", ComponentType.TEXT), ("Heading", ComponentType.HEADING),
                             ("Card", ComponentType.CARD), ("Container", ComponentType.CONTAINER)):
            button = CanvasToolButton(label, kind)
            button.clicked.connect(lambda checked=False, k=kind, b=button: self._choose_canvas_tool(k, b, checked))
            palette_row.addWidget(button)
            self._palette_buttons.append(button)
        self._align_buttons = {}
        for label, mode in (("Left", "left"), ("Center X", "center_x"), ("Right", "right"),
                            ("Top", "top"), ("Center Y", "center_y"), ("Bottom", "bottom")):
            button = QPushButton(label)
            button.setToolTip(f"Align selected components: {label.lower()}")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, m=mode: self.align_selection(m))
            palette_row.addWidget(button)
            self._align_buttons[mode] = button
        palette_row.addStretch(1)

        palette_frame = QWidget()
        palette_frame.setObjectName("canvasPalette")
        palette_frame.setMinimumWidth(1080)
        palette_frame.setLayout(palette_row)
        palette_scroll = QScrollArea()
        palette_scroll.setObjectName("paletteScroll")
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setFrameShape(QFrame.Shape.NoFrame)
        palette_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        palette_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        palette_scroll.setFixedHeight(50)
        palette_scroll.setWidget(palette_frame)

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(8, 8, 8, 8)
        central_layout.setSpacing(7)
        central_layout.addLayout(prompt_row)
        central_layout.addWidget(palette_scroll)
        central_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().addPermanentWidget(self.progress)

        self._build_actions()
        self._wire()
        self.generator.project_ready.connect(self._on_generated_project)
        self.generator.generation_failed.connect(self._on_generation_failed)
        self.generator.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self._refresh_all()

    def _on_generated_project(self, root: str) -> None:
        try:
            self.preview.attach_project(root)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Project files were created, but preview could not start: {exc}", 10000)
            return
        self.right_tabs.setCurrentWidget(self.preview)

    def _choose_canvas_tool(self, kind: ComponentType, selected: QPushButton, checked: bool) -> None:
        for button in self._palette_buttons:
            button.setChecked(button is selected and checked)
        self.canvas.set_tool(kind if checked else None)

    def _on_generation_failed(self, message: str) -> None:
        self.preview.show_error(message, "Project generation failed")
        self.right_tabs.setCurrentWidget(self.preview)

    # ------------------------------------------------------------------ actions
    def _action(self, text: str, slot, shortcut: str | QKeySequence.StandardKey | None = None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(lambda _checked=False: slot())
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        return act

    def _build_actions(self) -> None:
        self.act_import = self._action("Import sketch…", self.choose_sketch, QKeySequence.StandardKey.Open)
        self.act_open = self._action("Open project…", self.choose_project)
        self.act_save = self._action("Save project", self.save_project, QKeySequence.StandardKey.Save)
        self.act_save_as = self._action("Save project as…", lambda: self.save_project(as_new=True))
        self.act_export = self._action("Export design…", self.export_design)
        self.act_share = self._action("Share", self.show_share)
        self.act_quit = self._action("Quit", self.close, QKeySequence.StandardKey.Quit)
        self.act_undo = self._action("Undo", self.undo, QKeySequence.StandardKey.Undo)
        self.act_redo = self._action("Redo", self.redo, QKeySequence.StandardKey.Redo)
        self.act_delete = self._action("Delete selection", self.delete_selection, QKeySequence.StandardKey.Delete)
        self.act_fit = self._action("Fit to window", self.canvas.fit, "Ctrl+0")
        self.act_zoom_in = self._action("Zoom in", lambda: self.canvas.zoom(1.25), "Ctrl+=")
        self.act_zoom_out = self._action("Zoom out", lambda: self.canvas.zoom(0.8), "Ctrl+-")
        self.act_issues = QAction("Show issues on canvas", self, checkable=True, checked=True)
        self.act_issues.toggled.connect(self.canvas.set_show_issues)
        self.act_evaluate = self._action("Evaluate design", lambda: self._run(self.controller.evaluate), "Ctrl+E")
        self.act_repair = self._action("Auto-repair", self.correction._repair, "Ctrl+R")
        self.act_about = self._action("About", self.about)
        self.act_settings = self._action("Preferences…", self.show_settings, "Ctrl+,")

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.act_import)
        self.samples_menu = file_menu.addMenu("Open sample sketch")
        for path in self.controller.sample_sketches():
            act = QAction(path.stem.replace("_synthetic", "").replace("_", " "), self)
            act.triggered.connect(lambda _c=False, p=path: self.import_path(p))
            self.samples_menu.addAction(act)
        self.samples_menu.setEnabled(bool(self.controller.sample_sketches()))
        for act in (self.act_open, self.act_save, self.act_save_as, self.act_export):
            file_menu.addAction(act)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        edit = self.menuBar().addMenu("&Edit")
        edit.addActions([self.act_undo, self.act_redo, self.act_delete])
        edit.addSeparator()
        edit.addAction(self.act_settings)
        view = self.menuBar().addMenu("&View")
        view.addActions([self.act_fit, self.act_zoom_in, self.act_zoom_out])
        view.addSeparator()
        view.addAction(self.act_issues)
        tools = self.menuBar().addMenu("&Tools")
        tools.addActions([self.act_evaluate, self.act_repair])
        self.menuBar().addMenu("&Help").addAction(self.act_about)

        bar = self.addToolBar("Main")
        bar.setMovable(False)
        bar.addActions([self.act_import, self.act_save, self.act_undo, self.act_redo, self.act_fit,
                        self.act_evaluate, self.act_repair, self.act_share])

    def _wire(self) -> None:
        b = self.bridge
        b.project_opened.connect(self._on_project_opened)
        b.document_changed.connect(lambda *_: self._refresh_all())
        b.evaluation_changed.connect(lambda *_: self._on_evaluation())
        b.selection_changed.connect(lambda *_: self._on_selection())
        b.repair_started.connect(lambda: self.progress.start("repairing…"))
        b.repair_finished.connect(self._on_repair_finished)
        b.repair_event.connect(lambda name, data: self.progress.update_text(self._describe(name, data)))
        b.progress.connect(self.progress.update_text)
        b.error.connect(self._on_error)
        b.project_saved.connect(lambda p: self.statusBar().showMessage(f"saved to {p}", 5000))

        for source in (self.canvas, self.tree, self.correction, self.layer_panel):
            source.selection_requested.connect(self.controller.select)
        for source in (self.canvas, self.properties, self.correction, self.layer_panel, self.training, self.datasets):
            source.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))

    # ------------------------------------------------------------------ refresh
    def _refresh_all(self) -> None:
        self.canvas.reload()
        self.tree.rebuild()
        self.layer_panel.refresh()
        self.properties.refresh()
        self.correction.refresh()
        self.preview.refresh()
        self.sketch_view.refresh()
        self._update_actions()

    def _on_project_opened(self) -> None:
        self.workspace.request_fit()
        self.canvas._fit_pending = True
        self.progress.finish("")
        self._refresh_all()
        self.left_tabs.setCurrentWidget(self.tree)
        self.right_tabs.setCurrentWidget(self.properties)
        self.setWindowTitle(self._title())
        project = self.controller.project
        n = len(self.controller.document.components) - 1
        self.statusBar().showMessage(f"{project.name}: {n} components", 6000)

    def _on_evaluation(self) -> None:
        self.canvas.refresh_overlays()
        self.tree.rebuild()
        self.correction.refresh()

    def _on_selection(self) -> None:
        self.canvas.refresh_overlays()
        self.tree.sync_selection()
        self.layer_panel.sync_selection(self.controller.project.selection.primary
                                        if self.controller.has_project else None)
        self.properties.refresh()
        self._update_actions()
        selected = len(self.controller.project.selection.ids) if self.controller.has_project else 0
        self.statusBar().showMessage(f"{selected} component{'s' if selected != 1 else ''} selected" if selected else "Ready", 2500)

    def _on_repair_finished(self, report) -> None:
        self.progress.finish("")
        self.correction.on_repair_finished(report)
        self.right_tabs.setCurrentWidget(self.correction)
        self._refresh_all()

    def _on_error(self, message: str) -> None:
        self.progress.finish("")
        self.correction.on_repair_failed()
        self.statusBar().showMessage(message, 10000)

    @staticmethod
    def _describe(name: str, data: dict) -> str:
        return f"repair: {name} {data.get('issue', '')}".strip()

    def _title(self) -> str:
        if not self.controller.has_project:
            return f"SketchForge {__version__}"
        p = self.controller.project
        return f"{p.name}{' *' if p.dirty else ''} — SketchForge {__version__}"

    def _update_actions(self) -> None:
        has = self.controller.has_project
        self.edit_prompt.setEnabled(has)
        self.apply_prompt_button.setEnabled(has)
        for button in self._palette_buttons:
            button.setEnabled(has)
        selected = len(self.controller.project.selection.ids) if has else 0
        for button in self._align_buttons.values():
            button.setEnabled(selected > 1)
        self.act_delete.setEnabled(selected > 0)
        stack = self.controller.project.stack if has else None
        self.act_undo.setEnabled(bool(stack and stack.can_undo))
        self.act_redo.setEnabled(bool(stack and stack.can_redo))
        if stack is not None:
            self.act_undo.setToolTip(f"Undo: {stack.undo_label()}" if stack.can_undo else "Nothing to undo")
            self.act_redo.setToolTip(f"Redo: {stack.redo_label()}" if stack.can_redo else "Nothing to redo")
        self.act_delete.setEnabled(bool(has and self.controller.project.selection.ids))
        for act in (self.act_save, self.act_save_as, self.act_export, self.act_evaluate, self.act_repair, self.act_fit):
            act.setEnabled(has)
        self.setWindowTitle(self._title())

    # ------------------------------------------------------------------ user actions
    def _run(self, fn) -> None:
        try:
            fn()
        except SketchForgeError as exc:
            self.statusBar().showMessage(str(exc), 8000)

    def apply_prompt(self) -> None:
        """Parse a local natural-language edit and apply it as one undoable command."""
        instruction = self.edit_prompt.text().strip()
        if not instruction or not self.controller.has_project:
            return
        provider = self.controller.model_provider
        result = plan_with_model(provider, self.controller.document, instruction) if provider else None
        plan = result.plan if result and result.ok else None
        reason = result.reason if result and result.kind not in ("provider_error", "bad_output") else None
        if plan is None and reason is None:
            local = parse_instruction(instruction, self.controller.document)
            plan, reason = local.plan, local.reason
        if plan is None:
            self.statusBar().showMessage(reason or "Could not understand that edit.", 8000)
            return
        try:
            validate_plan(plan, self.controller.document)
            self.controller.execute(PlanCommand(plan))
        except SketchForgeError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            return
        self.edit_prompt.clear()
        explanation = plan.explanation or "Edit applied"
        self.statusBar().showMessage(explanation, 6000)

    def _selected_roots(self):
        ids = set(self.controller.project.selection.ids)
        doc = self.controller.document
        roots = []
        for cid in ids:
            comp = doc.require(cid)
            parent = doc.get(comp.parent_id or "")
            nested_selected = False
            while parent is not None and parent.id != doc.root_id:
                if parent.id in ids:
                    nested_selected = True
                    break
                parent = doc.get(parent.parent_id or "")
            if not nested_selected:
                roots.append(comp)
        return roots

    def nudge_selection(self, dx: float, dy: float) -> None:
        from sketchforge.editor.design_commands import CompositeCommand, MoveCommand
        if not self.controller.has_project or not self.controller.project.selection.ids:
            return
        cmds = [MoveCommand(c.id, dx, dy) for c in self._selected_roots()]
        self._run(lambda: self.controller.execute(CompositeCommand(cmds, "nudge selection")))

    def align_selection(self, mode: str) -> None:
        from sketchforge.design_ir.schema import BBox
        from sketchforge.editor.design_commands import CompositeCommand, SetBBoxCommand
        comps = self._selected_roots()
        if len(comps) < 2:
            return
        boxes = [c.bbox for c in comps]
        target = {"left": min(b.x for b in boxes), "center_x": sum(b.cx for b in boxes) / len(boxes),
                  "right": max(b.x2 for b in boxes), "top": min(b.y for b in boxes),
                  "center_y": sum(b.cy for b in boxes) / len(boxes), "bottom": max(b.y2 for b in boxes)}[mode]
        commands = []
        for comp in comps:
            b = comp.bbox
            x, y = b.x, b.y
            if mode == "left": x = target
            elif mode == "center_x": x = target - b.w / 2
            elif mode == "right": x = target - b.w
            elif mode == "top": y = target
            elif mode == "center_y": y = target - b.h / 2
            elif mode == "bottom": y = target - b.h
            if x != b.x or y != b.y:
                commands.append(SetBBoxCommand(comp.id, BBox(x=x, y=y, w=b.w, h=b.h)))
        if commands:
            self._run(lambda: self.controller.execute(CompositeCommand(commands, f"align selection {mode}")))

    def delete_selection(self) -> None:
        from sketchforge.editor.design_commands import CompositeCommand, RemoveComponentCommand
        roots = self._selected_roots() if self.controller.has_project else []
        if roots:
            self._run(lambda: self.controller.execute(CompositeCommand(
                [RemoveComponentCommand(c.id) for c in roots], "delete selection")))

    def choose_sketch(self) -> None:
        start = str(self.controller.sample_sketches()[0].parent) if self.controller.sample_sketches() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Import sketch", start, IMAGE_FILTER)
        if path:
            self.import_path(path)

    def import_path(self, path: str | Path) -> None:
        if not self.confirm_discard():
            return
        self.progress.start(f"importing {Path(path).name}…")
        self.controller.import_sketch_async(path)

    def choose_project(self) -> None:
        if not self.confirm_discard():
            return
        folder = QFileDialog.getExistingDirectory(self, "Open project folder")
        if folder:
            self._run(lambda: self.controller.open_project(folder))

    def save_project(self, as_new: bool = False) -> None:
        if not self.controller.has_project:
            return
        target = None if (as_new or self.controller.project.path is None) else self.controller.project.path
        if target is None:
            folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the project")
            if not folder:
                return
            target = Path(folder) / self.controller.project.name
        self._run(lambda: self.controller.save_project(target))
        self._update_actions()

    def export_design(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export design to folder")
        if folder:
            self._run(lambda: self.statusBar().showMessage(
                f"exported {', '.join(sorted(self.controller.export(folder)))} to {folder}", 8000))

    def undo(self) -> None:
        self._run(self.controller.undo)

    def redo(self) -> None:
        self._run(self.controller.redo)

    def about(self) -> None:
        QMessageBox.about(
            self, "About SketchForge",
            f"SketchForge {__version__}\n\nA local-first workbench from sketch to measured, editable design.\n"
            "Everything runs on this computer; the application makes no network requests.")

    def show_settings(self) -> None:
        """Open application preferences for the active controller."""
        SettingsDialog(self.controller, self).exec()

    def show_share(self) -> None:
        """Offer a clear, local-only preview link until public hosting is configured."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Share Project")
        dialog.setFixedWidth(410)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 18, 22, 20)
        heading = QHBoxLayout()
        title = QLabel("Share project")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        close = QPushButton("×")
        close.setFixedWidth(32)
        close.clicked.connect(dialog.reject)
        heading.addWidget(title, 1)
        heading.addWidget(close)
        layout.addLayout(heading)

        toggle = QCheckBox("Enable sharing & remixing")
        toggle.setChecked(False)
        layout.addWidget(toggle)
        access = QLabel("Only you can access this project")
        access.setObjectName("mutedText")
        layout.addWidget(access)
        notice = QLabel(
            "Your generated project is stored on this computer. Public sharing needs a hosting service. "
            "A local preview address only works on this device."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("background:#19181f;border:1px solid #ffffff22;border-radius:8px;padding:11px;color:#b6b3bd;")
        layout.addWidget(notice)
        copy = QPushButton("Copy local preview address")
        copy.setEnabled(False)
        layout.addWidget(copy)

        def update_access(enabled: bool) -> None:
            access.setText("Local preview link enabled for this device" if enabled else "Only you can access this project")
            copy.setEnabled(enabled and bool(self.preview._project_url))

        toggle.toggled.connect(update_access)
        def copy_address() -> None:
            QApplication.clipboard().setText(self.preview._project_url)
            self.statusBar().showMessage("Copied a local preview address. It works only on this device.", 7000)
            dialog.accept()
        copy.clicked.connect(copy_address)
        dialog.exec()

    def confirm_discard(self) -> bool:
        """True when it is safe to replace the open project (override in tests)."""
        if not (self.controller.has_project and self.controller.project.dirty):
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "Discard the unsaved changes to the open design?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if not self.confirm_discard():
            event.ignore()
            return
        self.workspace.sync_tabs(self.left_tabs, self.right_tabs)
        self.bridge.detach()
        self.preview._stop_server()
        self.controller.close()
        event.accept()


def _studio_stylesheet() -> str:
    """Dark, compact studio chrome inspired by the supplied Stitch references."""
    return """
    QMainWindow, QWidget { background: #111116; color: #eeedf3; font-family: 'Segoe UI', sans-serif; font-size: 12px; }
    QMenuBar { background: #0d0d11; color: #c9c7d0; border-bottom: 1px solid #ffffff19; padding: 4px; }
    QMenuBar::item { padding: 6px 10px; border-radius: 6px; }
    QMenuBar::item:selected, QMenu::item:selected { background: #2d2b36; }
    QMenu { background: #1c1b22; border: 1px solid #34323d; }
    QToolBar { background: #0d0d11; border: 0; border-bottom: 1px solid #ffffff19; spacing: 7px; padding: 5px 9px; }
    QToolButton, QPushButton { background: #24232b; color: #e8e6ee; border: 1px solid #ffffff1c; border-radius: 8px; padding: 7px 10px; }
    QToolButton:hover, QPushButton:hover { background: #302e39; border-color: #d9ff5f66; }
    QPushButton#paletteTool { background: #1a191f; border: 1px solid #ffffff20; border-radius: 9px; min-width: 62px; padding: 8px 10px; }
    QPushButton#paletteTool:checked { background: #353b25; color: #e7ff96; border-color: #d9ff5f99; }
    QPushButton#paletteTool:hover { background: #2a2932; }
    QPushButton#paletteTool:checked:hover { background: #414a2b; }
    QWidget#canvasPalette { background: #141419; }
    QScrollArea#paletteScroll { background: #141419; border: 1px solid #ffffff16; border-radius: 10px; }
    QScrollBar:horizontal { background: #15151a; height: 6px; margin: 0 8px; }
    QScrollBar::handle:horizontal { background: #3c3a45; min-width: 25px; border-radius: 3px; }
    QLabel#sectionEyebrow { color: #aaa7b2; font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 0 7px; }
    QToolButton:disabled, QPushButton:disabled { color: #77747e; }
    QTabWidget::pane { border: 1px solid #ffffff1a; border-radius: 10px; top: -1px; }
    QTabBar::tab { background: #17171d; color: #9996a2; padding: 9px 12px; margin: 3px 2px 0; border-radius: 7px; }
    QTabBar::tab:selected { background: #2a2932; color: #f2f0f7; }
    QSplitter::handle { background: #24232b; width: 1px; }
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox { background: #17171d; color: #ebe9f1; border: 1px solid #ffffff21; border-radius: 8px; padding: 7px 9px; selection-background-color: #596d29; }
    QCheckBox { color: #c8c5cf; spacing: 8px; }
    QCheckBox::indicator { width: 15px; height: 15px; }
    QCheckBox::indicator:checked { background: #d9ff5f; border: 1px solid #d9ff5f; border-radius: 4px; }
    QStatusBar { background: #0d0d11; color: #aaa7b2; border-top: 1px solid #ffffff16; }
    QScrollBar:vertical { background: #15151a; width: 9px; margin: 0; }
    QScrollBar::handle:vertical { background: #3c3a45; min-height: 25px; border-radius: 4px; }
    QLabel#eyebrow { color: #d9ff5f; font-size: 9px; font-weight: 700; letter-spacing: 1px; }
    QLabel#generationTitle { color: #f2f0f7; font-size: 20px; font-weight: 700; }
    QLabel#mutedText { color: #9d9aa6; font-size: 10px; }
    QPlainTextEdit#generationPrompt { background: #1b1a21; border: 1px solid #ffffff29; border-radius: 10px; padding: 10px; font-size: 11px; }
    QPushButton#generateButton { background: #d9ff5f; color: #17180f; border: 0; font-weight: 700; padding: 10px; }
    QPushButton#generateButton:hover { background: #e7ff96; }
    QPushButton#suggestionButton { background: #1b1a20; color: #c6c3ce; text-align: left; padding: 7px 9px; }
    QLabel#workspaceHint { color: #918e9b; background: #1a191f; border: 1px solid #ffffff15; border-radius: 9px; padding: 10px; font-size: 10px; }
    QWidget#previewControls { background: #18171d; border-bottom: 1px solid #ffffff18; }
    QLabel#previewEmptyState { color: #a6a3ae; font-size: 13px; line-height: 1.6; background: #101014; }
    QLabel#runtimeError { color: #ff9f9f; background: #351c22; padding: 8px; }
    """
