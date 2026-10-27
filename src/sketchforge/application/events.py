"""A tiny synchronous event bus.

Handlers run on the thread that emits. A GUI forwards events to its own thread (the Qt layer turns
them into signals). A handler that raises is logged and skipped so one bad subscriber cannot break
an operation.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)
Handler = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler: Handler) -> Callable[[], None]:
        with self._lock:
            self._handlers[event].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers[event]:
                    self._handlers[event].remove(handler)

        return unsubscribe

    def emit(self, event: str, **payload: Any) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event, ()))
        for handler in handlers:
            try:
                handler(**payload)
            except Exception:  # noqa: BLE001 - a subscriber must not break the emitter
                log.exception("handler for %r failed", event)
