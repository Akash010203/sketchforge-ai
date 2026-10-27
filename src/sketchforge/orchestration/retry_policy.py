"""Bounded retries for steps that can fail transiently (remote calls, file locks).

Deterministic local steps use ``RetryPolicy(max_attempts=1)``: retrying a deterministic failure
only repeats it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    retry_on: tuple[type[BaseException], ...] = (OSError, TimeoutError)

    def run(self, fn: Callable[[], T], sleep: Callable[[float], None] = time.sleep) -> T:
        attempt = 0
        while True:
            attempt += 1
            try:
                return fn()
            except self.retry_on:
                if attempt >= self.max_attempts:
                    raise
                sleep(self.backoff_seconds * attempt)
