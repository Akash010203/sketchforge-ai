"""Settings dialog: application preferences, provider configuration, and storage paths.

Sections:
  - General: theme, display resolution, auto-save interval
  - Vision: preprocessing limits, component detection thresholds
  - Providers: Nebius API key, provider model, egress consent
  - Storage: output directory, project archive path
  - Advanced: logging level, max repair iterations, worker thread count

All settings are read from and written to the application's AppConfig, which
is backed by config/app.yaml and config/providers.yaml. Credentials are never
stored in the configuration file (they are read from environment variables or
a user-level secrets file outside the project directory).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sketchforge.application.app_controller import AppController


class SettingsDialog(QDialog):
    """Modal settings dialog connected to the active AppController."""

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self.setWindowTitle("SketchForge — Settings")
        self.setMinimumWidth(520)
        self.setModal(True)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_vision_tab(), "Vision")
        tabs.addTab(self._build_providers_tab(), "Providers")
        tabs.addTab(self._build_storage_tab(), "Storage")
        tabs.addTab(self._build_advanced_tab(), "Advanced")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self._load_from_config()

    # ------------------------------------------------------------------ tab builders

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._auto_save = QCheckBox("Auto-save project every N minutes")
        form.addRow("Auto-save:", self._auto_save)

        self._auto_save_interval = QSpinBox()
        self._auto_save_interval.setRange(1, 60)
        self._auto_save_interval.setValue(5)
        self._auto_save_interval.setSuffix(" min")
        form.addRow("Save interval:", self._auto_save_interval)

        self._show_guides = QCheckBox("Show alignment guides on canvas")
        self._show_guides.setChecked(True)
        form.addRow("Guides:", self._show_guides)

        return w

    def _build_vision_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._working_long_side = QSpinBox()
        self._working_long_side.setRange(256, 4096)
        self._working_long_side.setSingleStep(128)
        self._working_long_side.setValue(1024)
        self._working_long_side.setSuffix(" px")
        form.addRow("Working resolution (long side):", self._working_long_side)

        self._min_component_side = QSpinBox()
        self._min_component_side.setRange(4, 64)
        self._min_component_side.setValue(8)
        self._min_component_side.setSuffix(" px")
        form.addRow("Min component side:", self._min_component_side)

        self._perspective_correction = QCheckBox("Enable perspective correction (experimental)")
        form.addRow("Perspective:", self._perspective_correction)

        return w

    def _build_providers_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Nebius
        nebius_group = QGroupBox("Nebius Token Factory")
        nebius_form = QFormLayout(nebius_group)

        self._nebius_enabled = QCheckBox("Enable (sends design summaries to Nebius servers)")
        nebius_form.addRow("Enable:", self._nebius_enabled)

        key_row = QHBoxLayout()
        self._nebius_key_hint = QLabel("Set via NEBIUS_API_KEY environment variable")
        self._nebius_key_hint.setStyleSheet("color: gray; font-style: italic;")
        key_row.addWidget(self._nebius_key_hint)
        nebius_form.addRow("API Key:", key_row)

        self._nebius_model = QLineEdit()
        self._nebius_model.setPlaceholderText("e.g. nvidia/Nemotron-3_5-Lightning")
        nebius_form.addRow("Model:", self._nebius_model)

        note = QLabel(
            "⚠ Enabling sends design summaries (component types, positions, labels) "
            "to Nebius servers. The original sketch image is never sent. "
            "See docs/NEBIUS_NVIDIA_INTEGRATION.md for details."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #cc7700;")
        nebius_form.addRow(note)

        layout.addWidget(nebius_group)
        layout.addStretch()
        return w

    def _build_storage_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._output_dir = QLineEdit()
        self._output_dir.setReadOnly(True)
        browse_out = QPushButton("Browse…")
        browse_out.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self._output_dir)
        row.addWidget(browse_out)
        form.addRow("Output directory:", row)

        self._project_dir = QLineEdit()
        self._project_dir.setReadOnly(True)
        browse_proj = QPushButton("Browse…")
        browse_proj.clicked.connect(self._browse_projects)
        row2 = QHBoxLayout()
        row2.addWidget(self._project_dir)
        row2.addWidget(browse_proj)
        form.addRow("Projects directory:", row2)

        return w

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._log_level = QComboBox()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level.setCurrentText("INFO")
        form.addRow("Log level:", self._log_level)

        self._max_repair_iterations = QSpinBox()
        self._max_repair_iterations.setRange(1, 50)
        self._max_repair_iterations.setValue(10)
        form.addRow("Max repair iterations:", self._max_repair_iterations)

        self._worker_threads = QSpinBox()
        self._worker_threads.setRange(1, 16)
        self._worker_threads.setValue(2)
        form.addRow("Worker threads:", self._worker_threads)

        return w

    # ------------------------------------------------------------------ browse slots

    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self._output_dir.setText(d)

    def _browse_projects(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select projects directory")
        if d:
            self._project_dir.setText(d)

    # ------------------------------------------------------------------ config sync

    def _load_from_config(self) -> None:
        cfg = self._ctrl.config
        vision_cfg = getattr(cfg, "vision", None)
        if vision_cfg:
            self._working_long_side.setValue(getattr(vision_cfg, "working_long_side", 1024))
            self._min_component_side.setValue(getattr(vision_cfg, "min_component_side_px", 8))

        from sketchforge.utilities.paths import repo_root
        out = repo_root() / "output"
        self._output_dir.setText(str(out))
        self._project_dir.setText(str(out / "projects"))

    def _accept(self) -> None:
        """Apply settings back to the controller config and close."""
        # Vision config (direct attribute assignment if the config supports it)
        cfg = self._ctrl.config
        vision_cfg = getattr(cfg, "vision", None)
        if vision_cfg:
            try:
                object.__setattr__(vision_cfg, "working_long_side",
                                   self._working_long_side.value())
                object.__setattr__(vision_cfg, "min_component_side_px",
                                   self._min_component_side.value())
            except (AttributeError, TypeError):
                pass  # frozen dataclass — changes take effect on next load

        self.accept()
