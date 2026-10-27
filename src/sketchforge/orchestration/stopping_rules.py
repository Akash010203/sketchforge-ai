"""Rules that end an improvement loop early."""

from __future__ import annotations


class StoppingRules:
    """Stop after ``no_progress_window`` consecutive attempts that did not improve anything."""

    def __init__(self, no_progress_window: int) -> None:
        self.window = no_progress_window
        self._streak = 0

    def record(self, improved: bool) -> None:
        self._streak = 0 if improved else self._streak + 1

    @property
    def streak(self) -> int:
        return self._streak

    def should_stop(self) -> str | None:
        if self._streak >= self.window:
            return f"no progress in {self.window} consecutive attempts"
        return None
