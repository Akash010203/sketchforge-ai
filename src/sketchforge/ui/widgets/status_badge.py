"""StatusBadge: a small coloured pill label for issue / state display."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

# Predefined severity → (background, foreground) colour pairs
_SEVERITY_PALETTE: dict[str, tuple[str, str]] = {
    "error":   ("#fef2f2", "#dc2626"),
    "warning": ("#fffbeb", "#d97706"),
    "info":    ("#eff6ff", "#2563eb"),
    "success": ("#f0fdf4", "#16a34a"),
    "neutral": ("#f9fafb", "#6b7280"),
}


class StatusBadge(QLabel):
    """A compact pill-shaped label with semantic colour coding.

    Usage::

        badge = StatusBadge("3 errors", severity="error")
        badge = StatusBadge("OK", severity="success")
        badge = StatusBadge("custom", bg="#ffeedd", fg="#333333")
    """

    def __init__(
        self,
        text: str = "",
        *,
        severity: str = "neutral",
        bg: str | None = None,
        fg: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._apply_style(severity, bg, fg)

    # ------------------------------------------------------------------ public

    def set_severity(self, severity: str) -> None:
        """Update the badge appearance for the given severity key."""
        self._apply_style(severity, None, None)

    def set_count(self, count: int, *, severity: str = "neutral", label: str = "") -> None:
        """Convenience: show a numeric count with the given severity."""
        suffix = f" {label}" if label else ""
        self.setText(f"{count}{suffix}")
        self._apply_style(severity if count else "success", None, None)

    # ------------------------------------------------------------------ internal

    def _apply_style(self, severity: str, bg: str | None, fg: str | None) -> None:
        default_bg, default_fg = _SEVERITY_PALETTE.get(severity, _SEVERITY_PALETTE["neutral"])
        bg = bg or default_bg
        fg = fg or default_fg
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {fg}40;"
            " border-radius:8px; padding:1px 7px; font-size:9pt; font-weight:600;"
        )
