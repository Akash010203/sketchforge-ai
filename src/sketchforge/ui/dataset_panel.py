"""Dataset panel: catalogue browser and synthetic-data generator.

Shows the full dataset registry in a two-section layout:
  Top  – Summary bar (total / eligible / local / synthetic count)
  Left – Table of manifest datasets with licence + availability status
  Right– Detail card for the selected dataset
  Bottom – "Generate synthetic data" helper with configurable count

The panel is self-contained: it loads the DatasetRegistry on demand
and never writes to the controller (datasets are off-project scope).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sketchforge.application.app_controller import AppController

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_STATUS_CSS = {
    "available": "color:#16a34a; font-weight:600;",
    "not downloaded": "color:#d97706; font-weight:600;",
    "local only": "color:#2563eb; font-weight:600;",
    "n/a": "color:#6b7280;",
}


def _status_label(entry_dict: dict) -> tuple[str, str]:
    """Return (text, css) for availability status."""
    if entry_dict.get("id") == "synthetic":
        n = entry_dict.get("sample_count", 0)
        return (f"{n} samples", _STATUS_CSS["local only"] if n else _STATUS_CSS["not downloaded"])
    if entry_dict.get("local_artifacts_present"):
        n = entry_dict.get("sample_count", 0)
        return (f"✔ local ({n} img)", _STATUS_CSS["available"])
    return ("⚠ not downloaded", _STATUS_CSS["not downloaded"])


# ---------------------------------------------------------------------------
# Background worker for synthetic generation
# ---------------------------------------------------------------------------


class _GenerateWorker(QThread):
    finished = Signal(bool, str)  # ok, message

    def __init__(self, count: int, parent=None) -> None:
        super().__init__(parent)
        self._count = count

    def run(self) -> None:
        script = Path(__file__).parents[4] / "scripts" / "generate_synthetic_data.py"
        if not script.is_file():
            self.finished.emit(False, f"Script not found: {script}")
            return
        try:
            result = subprocess.run(
                [sys.executable, str(script), "--count", str(self._count)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                self.finished.emit(True, f"Generated {self._count} samples.")
            else:
                self.finished.emit(False, result.stderr.strip() or "Generation failed.")
        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Timed out after 5 minutes.")
        except Exception as exc:
            self.finished.emit(False, str(exc))


# ---------------------------------------------------------------------------
# Summary bar
# ---------------------------------------------------------------------------


class _SummaryBar(QFrame):
    """Compact horizontal stats bar at the top of the panel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self._labels: dict[str, QLabel] = {}
        for key in ("total", "eligible", "local", "synthetic"):
            lbl = QLabel("—")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            container = QVBoxLayout()
            title = QLabel(key.capitalize())
            title.setStyleSheet("font-size:9pt; color:#6b7280;")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size:14pt; font-weight:700;")
            container.addWidget(title)
            container.addWidget(lbl)
            layout.addLayout(container)
            if key != "synthetic":
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                layout.addWidget(sep)
            self._labels[key] = lbl

    def update_summary(self, summary: dict) -> None:
        self._labels["total"].setText(str(summary.get("manifest_datasets", 0)))
        self._labels["eligible"].setText(str(summary.get("training_eligible", 0)))
        self._labels["local"].setText(str(summary.get("locally_available", 0)))
        self._labels["synthetic"].setText(str(summary.get("synthetic_samples", 0)))


# ---------------------------------------------------------------------------
# Detail card
# ---------------------------------------------------------------------------


class _DetailCard(QTextBrowser):
    """Right-side detail view for a selected dataset entry."""

    _PLACEHOLDER = "<p style='color:#9ca3af;'>Select a dataset to see details.</p>"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setHtml(self._PLACEHOLDER)

    def show_entry(self, entry: dict) -> None:
        if not entry:
            self.setHtml(self._PLACEHOLDER)
            return
        name = entry.get("name", entry.get("id", ""))
        eid = entry.get("id", "")
        lic = entry.get("license_spdx", "")
        access = entry.get("access", "")
        eligible = "✔ Yes" if entry.get("training_eligible") else "✗ No"
        status_txt, _ = _status_label(entry)
        url = entry.get("source_url") or ""
        url_html = f'<a href="{url}">{url}</a>' if url else "—"
        gib = entry.get("expected_gib")
        size_html = f"{gib} GiB" if gib else "unknown"
        data_dir = entry.get("data_dir", "")
        data_dir_html = f"<code>{data_dir}</code>" if data_dir else "—"
        samples = entry.get("sample_count", 0)

        html = f"""
<h3 style='margin-bottom:4px;'>{name}</h3>
<table cellspacing='6' style='font-size:10pt;'>
<tr><td><b>ID</b></td><td><code>{eid}</code></td></tr>
<tr><td><b>Licence</b></td><td>{lic or '—'}</td></tr>
<tr><td><b>Access</b></td><td>{access or '—'}</td></tr>
<tr><td><b>Training eligible</b></td><td>{eligible}</td></tr>
<tr><td><b>Local status</b></td><td>{status_txt}</td></tr>
<tr><td><b>Local samples</b></td><td>{samples}</td></tr>
<tr><td><b>Expected size</b></td><td>{size_html}</td></tr>
<tr><td><b>Source</b></td><td>{url_html}</td></tr>
<tr><td><b>Data dir</b></td><td>{data_dir_html}</td></tr>
</table>
"""
        self.setHtml(html)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class DatasetPanel(QWidget):
    """Browse, inspect and generate training datasets."""

    status_message = Signal(str)

    # Column indices in the catalogue table
    _COL_ID = 0
    _COL_NAME = 1
    _COL_LICENSE = 2
    _COL_STATUS = 3
    _COL_SAMPLES = 4

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self._entries: list[dict] = []
        self._worker: _GenerateWorker | None = None

        # ---- summary bar ----
        self._summary_bar = _SummaryBar()

        # ---- catalogue table ----
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["ID", "Name", "Licence", "Status", "Samples"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.currentCellChanged.connect(lambda r, c, pr, pc: self._on_row_changed(r))

        # ---- refresh button ----
        self._btn_refresh = QPushButton("↺ Refresh")
        self._btn_refresh.clicked.connect(self.refresh)

        table_container = QVBoxLayout()
        table_container.setContentsMargins(0, 0, 0, 0)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._btn_refresh)
        table_container.addLayout(btn_row)
        table_container.addWidget(self._table)

        table_widget = QWidget()
        table_widget.setLayout(table_container)

        # ---- detail card ----
        self._detail = _DetailCard()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(table_widget)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # ---- synthetic generator ----
        gen_group = QGroupBox("Generate synthetic training data")
        gen_layout = QHBoxLayout(gen_group)
        gen_layout.addWidget(QLabel("Count:"))
        self._spin_count = QSpinBox()
        self._spin_count.setRange(10, 50000)
        self._spin_count.setValue(500)
        self._spin_count.setSingleStep(100)
        gen_layout.addWidget(self._spin_count)
        self._btn_generate = QPushButton("▶ Generate")
        self._btn_generate.clicked.connect(self._start_generate)
        gen_layout.addWidget(self._btn_generate)
        self._gen_status = QLabel("")
        self._gen_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        gen_layout.addWidget(self._gen_status)

        # ---- main layout ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._summary_bar)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(gen_group)

        self.refresh()

    # ------------------------------------------------------------------ refresh

    def refresh(self) -> None:
        """Reload the DatasetRegistry and repopulate the table."""
        try:
            from sketchforge.datasets.registry import DatasetRegistry
            reg = DatasetRegistry.load()
        except Exception as exc:
            log.warning("DatasetPanel: could not load registry: %s", exc)
            self._entries = []
            self._table.setRowCount(0)
            self._detail.show_entry({})
            self._summary_bar.update_summary({})
            return

        self._summary_bar.update_summary(reg.summary())

        entries: list[dict] = []
        if reg.synthetic:
            entries.append(reg.synthetic.to_dict())
        for e in reg.entries:
            entries.append(e.to_dict())
        self._entries = entries

        self._table.setRowCount(0)
        for row, entry in enumerate(entries):
            self._table.insertRow(row)
            self._table.setItem(row, self._COL_ID, QTableWidgetItem(entry.get("id", "")))
            self._table.setItem(row, self._COL_NAME, QTableWidgetItem(entry.get("name", "")))
            self._table.setItem(row, self._COL_LICENSE, QTableWidgetItem(entry.get("license_spdx", "—")))

            status_txt, status_css = _status_label(entry)
            status_item = QTableWidgetItem(status_txt)
            status_item.setData(Qt.ItemDataRole.UserRole, status_css)
            lbl = QLabel(status_txt)
            lbl.setStyleSheet(status_css)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, self._COL_STATUS, lbl)
            self._table.setItem(row, self._COL_STATUS, status_item)

            self._table.setItem(
                row, self._COL_SAMPLES,
                QTableWidgetItem(str(entry.get("sample_count", 0)))
            )

        if entries:
            self._table.selectRow(0)

    # ------------------------------------------------------------------ slots

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._entries):
            self._detail.show_entry(self._entries[row])
        else:
            self._detail.show_entry({})

    def _start_generate(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        count = self._spin_count.value()
        self._btn_generate.setEnabled(False)
        self._gen_status.setText(f"Generating {count} samples…")
        self.status_message.emit(f"Generating {count} synthetic sketches…")
        self._worker = _GenerateWorker(count, self)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.start()

    @Slot(bool, str)
    def _on_generate_finished(self, ok: bool, message: str) -> None:
        self._btn_generate.setEnabled(True)
        self._gen_status.setText(message)
        self.status_message.emit(message)
        if not ok:
            QMessageBox.warning(self, "Generation failed", message)
        self.refresh()
