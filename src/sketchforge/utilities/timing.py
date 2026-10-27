"""Wall-clock timing helpers used for performance tracking."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class Stopwatch:
    """Accumulates named timings in milliseconds."""

    def __init__(self) -> None:
        self.timings_ms: dict[str, float] = {}

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            self.timings_ms[name] = self.timings_ms.get(name, 0.0) + elapsed

    def total_ms(self) -> float:
        return sum(self.timings_ms.values())

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 2) for k, v in self.timings_ms.items()}
