"""Background tasks, so the UI never blocks on image processing or repair.

Tasks run on a small thread pool. Callbacks are invoked **on the worker thread**; a UI adapts
them (the Qt layer converts them into signals). Nothing here knows about Qt.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Task(Generic[T]):
    id: int
    name: str
    status: str = "pending"  # pending | running | done | failed | cancelled
    result: T | None = None
    error: BaseException | None = None
    progress: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _future: Future | None = field(default=None, repr=False)

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed", "cancelled")


class TaskManager:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sketchforge")
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.tasks: dict[int, Task] = {}

    def submit(
        self,
        name: str,
        fn: Callable[[Task], T],
        *,
        on_done: Callable[[Task], None] | None = None,
        on_error: Callable[[Task], None] | None = None,
        on_progress: Callable[[Task], None] | None = None,
    ) -> Task[T]:
        task: Task[T] = Task(next(self._ids), name)
        with self._lock:
            self.tasks[task.id] = task

        def report(text: str) -> None:
            task.progress = text
            if on_progress:
                on_progress(task)

        task.report = report  # type: ignore[attr-defined]

        def run() -> None:
            task.status = "running"
            report("started")
            try:
                task.result = fn(task)
                task.status = "cancelled" if task.cancelled else "done"
                if on_done and task.status == "done":
                    on_done(task)
            except BaseException as exc:  # surfaced through the task, never lost in the pool
                task.error, task.status = exc, "failed"
                if on_error:
                    on_error(task)

        task._future = self._pool.submit(run)
        return task

    def wait(self, task: Task, timeout: float | None = None) -> Task:
        if task._future is not None:
            task._future.result(timeout)
        return task

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

    def active(self) -> list[Task]:
        return [t for t in self.tasks.values() if not t.finished]


def progress(task: Task, text: str) -> None:
    """Report progress from inside a task function."""
    getattr(task, "report", lambda _t: None)(text)


__all__ = ["Task", "TaskManager", "progress", "Any"]
