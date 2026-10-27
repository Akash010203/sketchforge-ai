"""Time and iteration budgets for loops that must not run forever."""

from __future__ import annotations

import time
from collections.abc import Callable


class Budget:
    """Wall-clock and iteration limits. ``exhausted`` returns the reason, or None while within budget."""

    def __init__(self, seconds: float, max_iterations: int,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.seconds, self.max_iterations, self._clock = seconds, max_iterations, clock
        self._start = clock()

    @property
    def elapsed(self) -> float:
        return self._clock() - self._start

    def exhausted(self, iterations_done: int) -> str | None:
        if iterations_done >= self.max_iterations:
            return f"iteration limit reached ({self.max_iterations})"
        if self.elapsed >= self.seconds:
            return f"time budget used up ({self.seconds:g}s)"
        return None
