"""Hierarchy view of the Design IR. Selecting a row selects the component on the canvas."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from sketchforge.application.app_controller import AppController
from sketchforge.design_ir.schema import Component

_ID_ROLE = Qt.ItemDataRole.UserRole
_SEVERITY_COLOR = {"error": "#dc2626", "warning": "#d97706", "info": "#2563eb"}
_RANK = {"error": 0, "warning": 1, "info": 2}


class ComponentTree(QTreeWidget):
    selection_requested = Signal(object)  # list of ids

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setHeaderLabels(["Component", "Type", "Issues"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setColumnWidth(0, 170)
        self.setColumnWidth(1, 70)
        self.setColumnWidth(2, 50)
        self.header().setStretchLastSection(False)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._syncing = False
        self.itemSelectionChanged.connect(self._on_selection)

    def rebuild(self) -> None:
        self._syncing = True
        self.clear()
        self._items = {}
        if self.controller.has_project:
            doc = self.controller.document
            issues = self._issue_map()
            for comp in doc.components:
                item = self._make_item(comp, issues.get(comp.id, []))
                self._items[comp.id] = item
            for comp in doc.components:  # attach in document order, so siblings keep their order
                item = self._items[comp.id]
                parent = self._items.get(comp.parent_id) if comp.parent_id else None
                (parent or self.invisibleRootItem()).addChild(item)
            self.expandAll()
        self._syncing = False
        self.sync_selection()

    def _issue_map(self) -> dict[str, list]:
        out: dict[str, list] = {}
        ev = self.controller.project.evaluation
        for issue in (ev.issues if ev else []):
            for cid in issue.component_ids:
                out.setdefault(cid, []).append(issue)
        return out

    def _make_item(self, comp: Component, issues: list) -> QTreeWidgetItem:
        label = comp.name or comp.id
        if comp.text and comp.type.value in ("text", "heading", "button", "input"):
            shown = comp.text if len(comp.text) <= 22 else comp.text[:21] + "…"
            label = f"{label}  “{shown}”"
        item = QTreeWidgetItem([label, comp.type.value, str(len(issues)) if issues else ""])
        item.setData(0, _ID_ROLE, comp.id)
        item.setToolTip(0, f"{comp.id}  ({comp.bbox.x:.0f}, {comp.bbox.y:.0f}) {comp.bbox.w:.0f}×{comp.bbox.h:.0f}"
                        + (f"\ndetection confidence {comp.detection.confidence:.2f}" if comp.detection else ""))
        if issues:
            worst = min(issues, key=lambda i: _RANK[i.severity]).severity
            item.setForeground(2, QBrush(QColor(_SEVERITY_COLOR[worst])))
            item.setToolTip(2, "\n".join(f"{i.code}: {i.message}" for i in issues))
        if not comp.visible:
            item.setForeground(0, QBrush(QColor("#94a3b8")))
        return item

    def sync_selection(self) -> None:
        if not self.controller.has_project:
            return
        self._syncing = True
        self.clearSelection()
        for cid in self.controller.project.selection.ids:
            item = self._items.get(cid)
            if item is not None:
                item.setSelected(True)
                self.scrollToItem(item)
        self._syncing = False

    def _on_selection(self) -> None:
        if self._syncing:
            return
        self.selection_requested.emit([i.data(0, _ID_ROLE) for i in self.selectedItems()])
