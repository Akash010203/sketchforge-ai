"""Measure, inject a known fault, auto-repair, and read the before/after report."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sketchforge.application.app_controller import AppController
from sketchforge.exceptions import SketchForgeError
from sketchforge.repair.error_injection import KINDS

_SEVERITY_COLOR = {"error": "#dc2626", "warning": "#d97706", "info": "#2563eb"}


class CorrectionPanel(QWidget):
    status_message = Signal(str)
    selection_requested = Signal(object)

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._pending_injection = None
        layout = QVBoxLayout(self)
        self.summary = QLabel("No design open.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        row = QHBoxLayout()
        self.kind_box = QComboBox()
        self.kind_box.addItems(KINDS)
        self.inject_btn = QPushButton("Inject fault")
        self.inject_btn.setToolTip("Deliberately break the design so the repair engine has something to find.")
        self.evaluate_btn = QPushButton("Evaluate")
        self.repair_btn = QPushButton("Auto-repair")
        self.repair_btn.setToolTip("Propose minimal patches, re-render, re-measure; accept only verified improvements.")
        for w in (self.kind_box, self.inject_btn, self.evaluate_btn, self.repair_btn):
            row.addWidget(w)
        layout.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Severity", "Issue", "Where", "Size"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 3)

        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlaceholderText("The before/after repair report appears here.")
        layout.addWidget(self.report_view, 4)

        self.inject_btn.clicked.connect(self._inject)
        self.evaluate_btn.clicked.connect(self._evaluate)
        self.repair_btn.clicked.connect(self._repair)
        self.table.itemSelectionChanged.connect(self._row_selected)
        self._issues: list = []
        self.refresh()

    # ------------------------------------------------------------------ actions
    def _guard(self, fn) -> None:
        try:
            fn()
        except SketchForgeError as exc:
            self.status_message.emit(str(exc))

    def _inject(self) -> None:
        def go() -> None:
            self._pending_injection = self.controller.inject_error(self.kind_box.currentText())
            self.status_message.emit(self._pending_injection.description)
        self._guard(go)

    def _evaluate(self) -> None:
        self._guard(self.controller.evaluate)

    def _repair(self) -> None:
        if not self.controller.has_project:
            return
        self.repair_btn.setEnabled(False)
        self.status_message.emit("repairing…")
        injection, self._pending_injection = self._pending_injection, None
        # run on a worker thread; the result arrives through the repair_finished event
        self.controller.run_repair_async(injection=injection)

    def on_repair_finished(self, report) -> None:
        self.repair_btn.setEnabled(True)
        self.report_view.setMarkdown(report.to_markdown())
        self.status_message.emit(report.headline())

    def on_repair_failed(self) -> None:
        self.repair_btn.setEnabled(True)

    # ------------------------------------------------------------------ display
    def refresh(self) -> None:
        has = self.controller.has_project
        for w in (self.inject_btn, self.evaluate_btn, self.repair_btn, self.kind_box):
            w.setEnabled(has)
        self.table.setRowCount(0)
        self._issues = []
        if not has:
            self.summary.setText("No design open.")
            return
        ev = self.controller.project.evaluation
        if ev is None:
            self.summary.setText("Not evaluated since the last edit. Press Evaluate.")
            return
        m = ev.metrics
        fid = (f"  ·  mean IoU vs sketch {m['fidelity_mean_iou']:.2f}" if "fidelity_mean_iou" in m else "")
        self.summary.setText(
            f"{int(m['issues_total'])} issue(s): {int(m['issues_error'])} error, "
            f"{int(m['issues_warning'])} warning, {int(m['issues_info'])} info{fid}")
        self._issues = list(ev.issues)
        self.table.setRowCount(len(self._issues))
        for r, issue in enumerate(self._issues):
            cells = [issue.severity, issue.code, ", ".join(issue.component_ids), f"{issue.measure:.1f} {issue.unit}"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(issue.message)
                if c == 0:
                    item.setForeground(QBrush(QColor(_SEVERITY_COLOR[issue.severity])))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def _row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows and rows[0].row() < len(self._issues):
            self.selection_requested.emit(list(self._issues[rows[0].row()].component_ids))
