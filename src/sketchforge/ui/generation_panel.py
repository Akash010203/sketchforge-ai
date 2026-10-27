"""Stitch-inspired prompt surface for generating complete application projects.

Changes in this revision:
  - Generation runs in a QThread so the UI stays responsive.
  - Live progress messages appear while the model works.
  - A follow-up / revise bar lets the user iterate on the generated project.
  - generate_studio_project now receives a progress callback.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sketchforge.generation.studio_generator import generate_studio_project
from sketchforge.utilities.paths import repo_root


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


class _GenerateWorker(QObject):
    """Runs generate_studio_project off the GUI thread."""

    progress = Signal(str)
    finished = Signal(str)   # project root path
    failed = Signal(str)     # error message

    def __init__(self, prompt: str, output_base: Path, include_backend: bool, options: dict, design_doc: object = None) -> None:
        super().__init__()
        self._prompt = prompt
        self._output_base = output_base
        self._include_backend = include_backend
        self._options = options
        self._design_doc = design_doc

    def run(self) -> None:  # called by QThread.started
        try:
            from sketchforge.generation.ai_generator import ai_generate_project
            self.progress.emit("Starting generation with Nemotron-3_5-Lightning…")
            root = ai_generate_project(
                self._prompt,
                self._output_base,
                include_backend=self._include_backend,
                design_doc=self._design_doc,
                progress=lambda msg: self.progress.emit(msg),
            )
            if not root or not Path(root).is_dir():
                self.progress.emit("AI service unavailable; generating from verified templates…")
                root = generate_studio_project(
                    self._prompt,
                    self._output_base,
                    include_backend=self._include_backend,
                    **self._options,
                    progress=lambda msg: self.progress.emit(msg),
                )
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(str(root))


class _ReviseWorker(QObject):
    """Runs ai_revise_project off the GUI thread."""

    progress = Signal(str)
    finished = Signal(bool)   # True = files updated

    def __init__(self, project_root: Path, instruction: str) -> None:
        super().__init__()
        self._root = project_root
        self._instruction = instruction

    def run(self) -> None:
        try:
            from sketchforge.generation.ai_generator import ai_revise_project
            ok = ai_revise_project(
                self._root,
                self._instruction,
                progress=lambda msg: self.progress.emit(msg),
            )
        except Exception as exc:  # noqa: BLE001
            self.progress.emit(f"Revision failed: {exc}")
            ok = False
        self.finished.emit(ok)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class GenerationPanel(QWidget):
    """Prompt-driven frontend and configurable backend project generator."""

    project_ready = Signal(str)
    generation_failed = Signal(str)
    status_message = Signal(str)

    def __init__(self, parent=None, controller=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("generationPanel")
        self._output_base = repo_root() / "output" / "projects"
        self._current_project_root: Path | None = None
        self._thread: QThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 14, 15, 14)
        layout.setSpacing(11)

        brand = QLabel("✳  SKETCHFORGE STUDIO")
        brand.setObjectName("eyebrow")
        layout.addWidget(brand)
        title = QLabel("What would you like\nto bring to life?")
        title.setObjectName("generationTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        intro = QLabel(
            "Start with an idea, a workflow, or a sketch. "
            "Your frontend and backend live together in one project."
        )
        intro.setObjectName("mutedText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("generationPrompt")
        self.prompt.setPlaceholderText("A warm, modern client portal for a small creative studio…")
        self.prompt.setFixedHeight(130)
        layout.addWidget(self.prompt)

        self.backend = QCheckBox("Add a backend")
        self.backend.setChecked(True)
        self.backend.setToolTip(
            "Choose the database, ORM, API framework, authentication, and migration options below."
        )
        layout.addWidget(self.backend)

        self.database_target = QComboBox()
        self.database_target.addItems(["SQLite", "PostgreSQL", "MySQL"])
        self.orm_target = QComboBox()
        self.orm_target.addItems(["Dataclass", "SQLAlchemy", "Prisma"])
        self.api_target = QComboBox()
        self.api_target.addItems(["Flask", "FastAPI", "GraphQL"])
        self.auth_option = QCheckBox("Add password, JWT sessions, and Google OAuth2")
        self.migrations_option = QCheckBox("Add database migrations")
        for label, control in (("Database", self.database_target), ("ORM", self.orm_target),
                               ("API", self.api_target)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(control)
            layout.addLayout(row)
        layout.addWidget(self.auth_option)
        layout.addWidget(self.migrations_option)
        self.backend.toggled.connect(self._set_backend_controls)
        self.orm_target.currentIndexChanged.connect(self._set_migration_availability)
        self.database_target.currentIndexChanged.connect(self._set_migration_availability)
        self._set_migration_availability()

        self.generate_button = QPushButton("✦   Generate full stack")
        self.generate_button.setObjectName("generateButton")
        self.generate_button.clicked.connect(self.generate)
        layout.addWidget(self.generate_button)

        # Progress label — shows streaming messages during generation
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("mutedText")
        self.progress_label.setWordWrap(True)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        row = QHBoxLayout()
        self.choose_button = QPushButton("Choose output folder…")
        self.choose_button.setObjectName("quietButton")
        self.choose_button.clicked.connect(self.choose_output_folder)
        self.output_label = QLabel("output/projects")
        self.output_label.setObjectName("mutedText")
        self.output_label.setWordWrap(True)
        row.addWidget(self.choose_button)
        layout.addLayout(row)
        layout.addWidget(self.output_label)

        separator = QLabel("✦  QUICK STARTS")
        separator.setObjectName("eyebrow")
        layout.addSpacing(6)
        layout.addWidget(separator)
        for suggestion in (
            "A simple dashboard for tracking my team projects",
            "A booking page for a neighborhood coffee shop",
            "A personal finance tracker with monthly goals",
        ):
            button = QPushButton(suggestion)
            button.setObjectName("suggestionButton")
            button.setMinimumHeight(42)
            button.setStyleSheet("text-align: left; white-space: normal;")
            button.clicked.connect(
                lambda _checked=False, text=suggestion: self.prompt.setPlainText(text)
            )
            layout.addWidget(button)

        # --- Follow-up / revise section (hidden until a project is ready) ---
        self.revise_separator = QLabel("✦  REVISE PROJECT")
        self.revise_separator.setObjectName("eyebrow")
        self.revise_separator.setVisible(False)
        layout.addSpacing(6)
        layout.addWidget(self.revise_separator)

        self.revise_prompt = QPlainTextEdit()
        self.revise_prompt.setObjectName("generationPrompt")
        self.revise_prompt.setPlaceholderText(
            "Describe a change, e.g. \"Add a dark-mode toggle\" or \"Change accent color to blue\""
        )
        self.revise_prompt.setFixedHeight(72)
        self.revise_prompt.setVisible(False)
        layout.addWidget(self.revise_prompt)

        self.revise_button = QPushButton("↻   Apply revision")
        self.revise_button.setObjectName("generateButton")
        self.revise_button.setVisible(False)
        self.revise_button.clicked.connect(self.revise)
        layout.addWidget(self.revise_button)

        layout.addStretch(1)
        self.recent = QLabel(
            "YOUR WORKSPACE\n\nGenerated projects appear in the preview and project folder."
        )
        self.recent.setObjectName("workspaceHint")
        self.recent.setWordWrap(True)
        layout.addWidget(self.recent)

    def _set_backend_controls(self, enabled: bool) -> None:
        for control in (self.database_target, self.orm_target, self.api_target,
                        self.auth_option, self.migrations_option):
            control.setEnabled(enabled)
        self._set_migration_availability()

    def _set_migration_availability(self, *_args) -> None:
        orm = self.orm_target.currentText().lower()
        database = self.database_target.currentText().lower()
        if orm == "prisma" and self.auth_option.isChecked():
            self.auth_option.setChecked(False)
        self.migrations_option.setEnabled(
            self.backend.isChecked() and (orm in {"sqlalchemy", "prisma"} or database != "sqlite")
        )
        self.auth_option.setEnabled(self.backend.isChecked() and orm != "prisma")
        self.api_target.setEnabled(self.backend.isChecked() and orm != "prisma")

    # ------------------------------------------------------------------
    def choose_output_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose generated project folder", str(self._output_base)
        )
        if path:
            self._output_base = Path(path)
            self.output_label.setText(str(self._output_base))

    def generate(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self.status_message.emit("Add a short description before generating your app.")
            self.prompt.setFocus()
            return

        self._set_busy(True)
        self.progress_label.setText("Starting…")
        self.progress_label.setVisible(True)

        options = {
            "database": self.database_target.currentText().lower(),
            "orm": self.orm_target.currentText().lower(),
            "api_target": self.api_target.currentText().lower(),
            "authentication": self.auth_option.isChecked(),
            "migrations": self.migrations_option.isChecked(),
        }
        design_doc = self.controller.document if self.controller and self.controller.has_project else None
        worker = _GenerateWorker(prompt, self._output_base, self.backend.isChecked(), options, design_doc=design_doc)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_generate_done)
        worker.failed.connect(self._on_generate_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def revise(self) -> None:
        if self._current_project_root is None:
            self.status_message.emit("Generate a project first before applying a revision.")
            return
        instruction = self.revise_prompt.toPlainText().strip()
        if not instruction:
            self.status_message.emit("Describe what you'd like to change.")
            self.revise_prompt.setFocus()
            return

        self._set_busy(True)
        self.progress_label.setText("Sending revision to AI…")
        self.progress_label.setVisible(True)

        worker = _ReviseWorker(self._current_project_root, instruction)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_revise_done)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    # ------------------------------------------------------------------
    def _on_progress(self, msg: str) -> None:
        self.progress_label.setText(msg)
        self.status_message.emit(msg)

    def _on_generate_done(self, root_str: str) -> None:
        root = Path(root_str)
        self._current_project_root = root
        n = len(list(root.rglob("*.*")))
        self.recent.setText(
            f"LATEST PROJECT\n\n{root.name}\n{n} generated files\n{root}"
        )
        backend_label = "SQLite backend scaffold" if self.backend.isChecked() else "no backend"
        self.status_message.emit(f"Generated {root.name} with frontend and {backend_label}.")
        self.progress_label.setVisible(False)
        self._set_busy(False)
        self._show_revise(True)
        self.project_ready.emit(root_str)

    def _on_generate_failed(self, message: str) -> None:
        self.status_message.emit(f"Could not generate the project: {message}")
        self.generation_failed.emit(message)
        self.progress_label.setVisible(False)
        self._set_busy(False)

    def _on_revise_done(self, updated: bool) -> None:
        if updated:
            self.status_message.emit("Revision applied — refreshing preview…")
            if self._current_project_root:
                self.project_ready.emit(str(self._current_project_root))
        else:
            self.status_message.emit("Revision could not be applied (AI returned no changes).")
        self.revise_prompt.clear()
        self.progress_label.setVisible(False)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled(not busy)
        self.generate_button.setText(
            "◌   Building your project…" if busy else "✦   Generate full stack"
        )
        self.revise_button.setEnabled(not busy)
        self.choose_button.setEnabled(not busy)

    def _show_revise(self, visible: bool) -> None:
        self.revise_separator.setVisible(visible)
        self.revise_prompt.setVisible(visible)
        self.revise_button.setVisible(visible)
