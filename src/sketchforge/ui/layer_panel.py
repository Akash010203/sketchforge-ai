"""Layer panel: component z-order and visibility management.

Displays all components in the open document as a flat ordered list
(bottom layer at the top of the list, consistent with most design tools).
The user can:
  - Toggle component visibility (eye icon)
  - Toggle lock state (lock icon)
  - Re-order layers by drag-and-drop (planned; Ctrl+[ / Ctrl+] shortcuts work now)
  - Double-click a layer name to rename it (edits the component label property)
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sketchforge.application.app_controller import AppController
from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.schema import ComponentType, DesignDocument
from sketchforge.editor.layer_operations import reorder


# Map component type → icon label (fallback until real icon assets exist)
_TYPE_ICON: dict[ComponentType, str] = {
    ComponentType.BUTTON: "⬛",
    ComponentType.INPUT: "⬜",
    ComponentType.TEXT: "T",
    ComponentType.HEADING: "H",
    ComponentType.IMAGE: "🖼",
    ComponentType.CARD: "▭",
    ComponentType.CONTAINER: "▭",
    ComponentType.HEADER: "▬",
    ComponentType.FOOTER: "▬",
    ComponentType.SIDEBAR: "▏",
    ComponentType.DIVIDER: "—",
    ComponentType.CHECKBOX: "☑",
    ComponentType.RADIO: "◎",
}


class _LayerItem(QListWidgetItem):
    def __init__(self, comp_id: str, label: str, type_icon: str, visible: bool, locked: bool):
        super().__init__()
        self.comp_id = comp_id
        self._label = label
        self._type_icon = type_icon
        self._visible = visible
        self._locked = locked
        self._refresh_text()

    def _refresh_text(self) -> None:
        vis = "👁" if self._visible else "🚫"
        lock = "🔒" if self._locked else "  "
        self.setText(f"{vis} {lock}  {self._type_icon}  {self._label}")
        self.setToolTip(f"ID: {self.comp_id}")
        color = Qt.GlobalColor.white if self._visible else Qt.GlobalColor.gray
        self.setForeground(color)


class LayerPanel(QWidget):
    """Flat, reverse-ordered layer list for the open design document."""

    selection_requested = Signal(str)  # component id
    status_message = Signal(str)

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Tool buttons
        self._btn_vis = QToolButton()
        self._btn_vis.setText("👁 Toggle Visibility")
        self._btn_vis.setToolTip("Toggle visibility of selected component (V)")
        self._btn_vis.clicked.connect(self._toggle_visibility)

        self._btn_lock = QToolButton()
        self._btn_lock.setText("🔒 Toggle Lock")
        self._btn_lock.setToolTip("Toggle lock state of selected component (L)")
        self._btn_lock.clicked.connect(self._toggle_lock)

        self._btn_up = QPushButton("↑")
        self._btn_up.setFixedWidth(32)
        self._btn_up.setToolTip("Move layer up (Ctrl+])")
        self._btn_up.clicked.connect(self._move_up)

        self._btn_down = QPushButton("↓")
        self._btn_down.setFixedWidth(32)
        self._btn_down.setToolTip("Move layer down (Ctrl+[)")
        self._btn_down.clicked.connect(self._move_down)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(self._btn_vis)
        toolbar.addWidget(self._btn_lock)
        toolbar.addStretch()
        toolbar.addWidget(self._btn_up)
        toolbar.addWidget(self._btn_down)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel("Layers"))
        layout.addLayout(toolbar)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        """Rebuild the layer list from the current document."""
        self._list.clear()
        if not self._ctrl.has_project:
            return
        doc = self._ctrl.document
        # Reverse so bottom layers are at top of list (design-tool convention)
        comps = list(preorder(doc))
        comps.reverse()
        for comp in comps:
            if comp.id == doc.root_id:
                continue
            icon = _TYPE_ICON.get(comp.type, "◻")
            label = comp.name or comp.text or comp.id
            item = _LayerItem(comp.id, label, icon, comp.visible, comp.locked)
            self._list.addItem(item)

    def sync_selection(self, comp_id: str | None) -> None:
        """Highlight the item matching ``comp_id``."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if isinstance(item, _LayerItem) and item.comp_id == comp_id:
                self._list.setCurrentItem(item)
                self._list.scrollToItem(item)
                return
        self._list.clearSelection()

    # ------------------------------------------------------------------ slots
    def _selected_id(self) -> str | None:
        item = self._list.currentItem()
        return item.comp_id if isinstance(item, _LayerItem) else None

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if isinstance(item, _LayerItem):
            self.selection_requested.emit(item.comp_id)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if isinstance(item, _LayerItem):
            self.status_message.emit(
                f"Double-click rename: use Properties panel to rename '{item.comp_id}'"
            )

    def _toggle_visibility(self) -> None:
        cid = self._selected_id()
        if not cid:
            return
        try:
            doc = self._ctrl.document
            comp = doc.get(cid)
            if comp is None:
                return
            self._ctrl.set_property(cid, "visible", not comp.visible)
            self.refresh()
            self.status_message.emit(
                f"{'Showed' if not comp.visible else 'Hidden'}: {cid}"
            )
        except Exception as exc:
            self.status_message.emit(f"Error: {exc}")

    def _toggle_lock(self) -> None:
        cid = self._selected_id()
        if not cid:
            return
        try:
            doc = self._ctrl.document
            comp = doc.get(cid)
            if comp is None:
                return
            self._ctrl.set_property(cid, "locked", not comp.locked)
            self.refresh()
            self.status_message.emit(
                f"{'Locked' if not comp.locked else 'Unlocked'}: {cid}"
            )
        except Exception as exc:
            self.status_message.emit(f"Error: {exc}")

    def _move_up(self) -> None:
        self._reorder_selected("up")

    def _move_down(self) -> None:
        self._reorder_selected("down")

    def _reorder_selected(self, direction: str) -> None:
        cid = self._selected_id()
        if not cid:
            return
        try:
            command = reorder(self._ctrl.document, cid, direction)
            if not command.commands:
                return
            self._ctrl.execute(command)
            self.refresh()
            self.sync_selection(cid)
            self.status_message.emit(f"Moved layer {direction}: {cid}")
        except Exception as exc:
            self.status_message.emit(f"Error: {exc}")
