"""Workspace state – split out from main_window to keep it focused.

WorkspaceState owns the UI-level projection of the open project:
  - Which left / right tab is active
  - Pending fit-to-window flag
  - Convenience helpers for workspace-wide refresh coordination

``MainWindow`` holds *one* ``WorkspaceState`` instance and delegates all
tab-tracking / fit logic to it.  The state object has no Qt signal coupling
so it can be tested without a running QApplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTabWidget


@dataclass
class WorkspaceState:
    """Mutable UI workspace state; kept separate from MainWindow layout code."""

    # True until the first project is loaded and the canvas has been fitted.
    fit_pending: bool = True

    # Index of the active left / right tab (persists across refreshes).
    left_tab_index: int = 0
    right_tab_index: int = 0

    # Last status message shown to the user (for tests / accessibility).
    last_status: str = ""

    # ------------------------------------------------------------------ helpers

    def request_fit(self) -> None:
        """Schedule a fit-to-window on the next canvas reload."""
        self.fit_pending = True

    def consume_fit(self) -> bool:
        """Return True (and clear the flag) if a fit is pending."""
        if self.fit_pending:
            self.fit_pending = False
            return True
        return False

    def sync_tabs(self, left: "QTabWidget", right: "QTabWidget") -> None:
        """Persist the currently-active tab indices from the live widgets."""
        self.left_tab_index = left.currentIndex()
        self.right_tab_index = right.currentIndex()

    def restore_tabs(self, left: "QTabWidget", right: "QTabWidget") -> None:
        """Restore the last-active tab indices into the live widgets."""
        if 0 <= self.left_tab_index < left.count():
            left.setCurrentIndex(self.left_tab_index)
        if 0 <= self.right_tab_index < right.count():
            right.setCurrentIndex(self.right_tab_index)
