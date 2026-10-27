"""Status-bar widget: a busy indicator plus the latest progress text."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget


class TaskProgress(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # indeterminate
        self.bar.setMaximumWidth(120)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

    def start(self, text: str) -> None:
        self.label.setText(text)
        self.bar.show()

    def update_text(self, text: str) -> None:
        if text:
            self.label.setText(text)

    def finish(self, text: str = "") -> None:
        self.bar.hide()
        self.label.setText(text)

    @property
    def busy(self) -> bool:
        return not self.bar.isHidden()
