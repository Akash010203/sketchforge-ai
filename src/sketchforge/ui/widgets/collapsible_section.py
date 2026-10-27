"""CollapsibleSection: a titled panel that can be expanded/collapsed."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QWidget):
    """A vertically-stacked widget with a clickable header to expand/collapse.

    Usage::

        section = CollapsibleSection("Advanced options")
        section.add_widget(some_form)
        section.add_widget(another_widget)
        layout.addWidget(section)

    The section starts expanded by default; pass ``expanded=False`` to start
    collapsed.
    """

    _ARROW_OPEN = "▾"
    _ARROW_CLOSED = "▸"

    _HEADER_STYLE = (
        "QToolButton {"
        "  background: transparent;"
        "  border: none;"
        "  font-weight: 600;"
        "  font-size: 10pt;"
        "  text-align: left;"
        "  padding: 4px 2px;"
        "}"
        "QToolButton:hover { color: #2563eb; }"
    )

    _SEP_STYLE = "background: #e5e7eb;"

    def __init__(self, title: str = "", *, expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._expanded = expanded

        # Header
        self._toggle = QToolButton()
        self._toggle.setStyleSheet(self._HEADER_STYLE)
        self._toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toggle.clicked.connect(self._on_toggle)
        self._set_header_text(title)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(self._SEP_STYLE)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self._toggle)

        # Content area
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 2, 2, 4)
        self._content_layout.setSpacing(4)
        self._content.setVisible(expanded)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addLayout(header_row)
        main.addWidget(sep)
        main.addWidget(self._content)

    # ------------------------------------------------------------------ public

    def add_widget(self, widget: QWidget) -> None:
        """Append a widget to the collapsible content area."""
        self._content_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._set_header_text(self._toggle.text().split(" ", 1)[-1])

    def is_expanded(self) -> bool:
        return self._expanded

    # ------------------------------------------------------------------ internal

    def _set_header_text(self, title: str) -> None:
        arrow = self._ARROW_OPEN if self._expanded else self._ARROW_CLOSED
        self._toggle.setText(f"{arrow}  {title}")

    def _on_toggle(self) -> None:
        self.set_expanded(not self._expanded)
