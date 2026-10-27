"""IconToolButton: a QToolButton with consistent sizing and hover styling."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QToolButton


class IconToolButton(QToolButton):
    """A consistently-sized tool button designed for use in panel toolbars.

    Provides:
    - Fixed icon size so toolbars align across panels.
    - CSS hover highlight via stylesheet.
    - Optional ``tooltip`` shorthand in the constructor.

    Usage::

        btn = IconToolButton("👁", tooltip="Toggle visibility")
        btn.clicked.connect(my_slot)
    """

    _DEFAULT_SIZE = QSize(28, 28)

    _STYLE = (
        "QToolButton {"
        "  border: none;"
        "  border-radius: 4px;"
        "  padding: 2px 4px;"
        "}"
        "QToolButton:hover {"
        "  background: rgba(0,0,0,0.08);"
        "}"
        "QToolButton:pressed {"
        "  background: rgba(0,0,0,0.14);"
        "}"
        "QToolButton:checked {"
        "  background: rgba(37,99,235,0.15);"
        "  color: #2563eb;"
        "}"
    )

    def __init__(
        self,
        text: str = "",
        *,
        tooltip: str = "",
        checkable: bool = False,
        size: QSize | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        if tooltip:
            self.setToolTip(tooltip)
        self.setCheckable(checkable)
        self.setFixedSize(size or self._DEFAULT_SIZE)
        self.setStyleSheet(self._STYLE)
