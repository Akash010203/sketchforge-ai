"""Edit the selected component: text, colours, position, size, font.

Every change is a controller command (so it is validated, undoable and reflected everywhere).
A rejected edit (locked component, invalid value) is reported and the field snaps back.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from sketchforge.application.app_controller import AppController
from sketchforge.design_ir.schema import Component
from sketchforge.exceptions import SketchForgeError

_TEXT_TYPES = {"text", "heading", "button", "input", "checkbox", "radio"}


def _spin(maximum: float = 5000.0, minimum: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(1)
    box.setSingleStep(1.0)
    box.setKeyboardTracking(False)
    return box


class ColorButton(QPushButton):
    color_chosen = Signal(str)

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title, self._value = title, "#000000"
        self.clicked.connect(self._pick)

    def set_value(self, value: str | None) -> None:
        self._value = value or "#000000"
        c = QColor(self._value)
        shown = c.name() if c.isValid() else (value or "none")
        if c.isValid():
            fg = "#000000" if c.lightness() > 140 else "#ffffff"
            self.setStyleSheet(f"background:{c.name()}; color:{fg}; padding:4px;")
        else:
            self.setStyleSheet("padding:4px;")
        self.setText(shown)

    def _pick(self) -> None:
        start = QColor(self._value) if QColor(self._value).isValid() else QColor("#ffffff")
        chosen = QColorDialog.getColor(start, self, self._title)
        if chosen.isValid():
            self.color_chosen.emit(chosen.name())


class PropertiesPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._loading = False
        self._current: str | None = None
        form = QFormLayout(self)
        self.id_label, self.type_label, self.conf_label = QLabel("—"), QLabel("—"), QLabel("—")
        self.name_edit, self.text_edit = QLineEdit(), QLineEdit()
        self.x_spin, self.y_spin = _spin(), _spin()
        self.w_spin, self.h_spin = _spin(minimum=1.0), _spin(minimum=1.0)
        self.font_spin = _spin(200.0, 1.0)
        self.radius_spin = _spin(500.0)
        self.fill_btn, self.text_color_btn = ColorButton("Fill colour"), ColorButton("Text colour")
        self.stroke_btn = ColorButton("Border colour")
        for label, widget in (
            ("ID", self.id_label), ("Type", self.type_label), ("Detection", self.conf_label),
            ("Name", self.name_edit), ("Text", self.text_edit),
            ("X", self.x_spin), ("Y", self.y_spin), ("Width", self.w_spin), ("Height", self.h_spin),
            ("Fill", self.fill_btn), ("Border", self.stroke_btn), ("Text colour", self.text_color_btn),
            ("Font size", self.font_spin), ("Corner radius", self.radius_spin),
        ):
            form.addRow(label, widget)
        self.name_edit.editingFinished.connect(lambda: self._commit("name", self.name_edit.text()))
        self.text_edit.editingFinished.connect(lambda: self._commit("text", self.text_edit.text()))
        for prop, spin in (("x", self.x_spin), ("y", self.y_spin), ("width", self.w_spin),
                           ("height", self.h_spin), ("font_size", self.font_spin),
                           ("corner_radius", self.radius_spin)):
            spin.valueChanged.connect(lambda v, p=prop: self._commit(p, v))
        self.fill_btn.color_chosen.connect(lambda c: self._commit("fill", c))
        self.stroke_btn.color_chosen.connect(lambda c: self._commit("stroke", c))
        self.text_color_btn.color_chosen.connect(lambda c: self._commit("color", c))
        self.refresh()

    # ------------------------------------------------------------------ data flow
    def refresh(self) -> None:
        comp = self._selected()
        self._current = comp.id if comp else None
        self._loading = True
        enabled = comp is not None
        for w in (self.name_edit, self.text_edit, self.x_spin, self.y_spin, self.w_spin, self.h_spin,
                  self.fill_btn, self.stroke_btn, self.text_color_btn, self.font_spin, self.radius_spin):
            w.setEnabled(enabled)
        if comp is None:
            self.id_label.setText("nothing selected")
            self.type_label.setText("—")
            self.conf_label.setText("—")
            self._loading = False
            return
        self.id_label.setText(comp.id + ("  🔒" if comp.locked else ""))
        self.type_label.setText(comp.type.value)
        det = comp.detection
        self.conf_label.setText(
            f"{det.confidence:.2f}" + ("  (ambiguous type)" if getattr(det, "ambiguous", False) else "")
            if det else "created in the editor")
        self.name_edit.setText(comp.name or "")
        carries_text = comp.type.value in _TEXT_TYPES and "text" in comp.editable
        self.text_edit.setEnabled(carries_text and not comp.locked)
        self.text_edit.setText(comp.text or "")
        self.text_edit.setPlaceholderText("")
        if comp.text_is_inferred and comp.text:
            self.text_edit.setToolTip("Placeholder: the sketch's handwriting was not read. Type the real text.")
        else:
            self.text_edit.setToolTip("")
        b = comp.bbox
        for spin, v in ((self.x_spin, b.x), (self.y_spin, b.y), (self.w_spin, b.w), (self.h_spin, b.h)):
            spin.setValue(v)
        self.fill_btn.set_value(comp.style.fill)
        self.stroke_btn.set_value(comp.style.stroke)
        self.radius_spin.setValue(comp.style.corner_radius or 0.0)
        has_type = comp.typography is not None
        self.font_spin.setEnabled(has_type and not comp.locked)
        self.text_color_btn.setEnabled(has_type and not comp.locked)
        self.font_spin.setValue(comp.typography.font_size if has_type else 1.0)
        self.text_color_btn.set_value(comp.typography.color if has_type else None)
        self._loading = False

    def _selected(self) -> Component | None:
        if not self.controller.has_project:
            return None
        pid = self.controller.project.selection.primary
        return self.controller.document.get(pid) if pid else None

    def _commit(self, prop: str, value) -> None:
        if self._loading or self._current is None:
            return
        comp = self.controller.document.get(self._current)
        if comp is None:
            return
        try:
            if prop in ("x", "y", "width", "height") and self._unchanged(comp, prop, float(value)):
                return
            self.controller.edit_property(self._current, prop, value)
        except SketchForgeError as exc:
            self.status_message.emit(str(exc))
            self.refresh()  # snap the field back to the real value

    @staticmethod
    def _unchanged(comp: Component, prop: str, value: float) -> bool:
        b = comp.bbox
        current = {"x": b.x, "y": b.y, "width": b.w, "height": b.h}[prop]
        return abs(current - value) < 0.05
