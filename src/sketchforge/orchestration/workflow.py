"""Run an ordered list of named steps over a :class:`WorkflowState`.

A step is ``fn(state) -> detail | None``; it reads its inputs from ``state.context`` and writes its
outputs back. The runner times every step, records it in the history, honours cancellation between
steps and converts an exception into a FAILED state that names the step.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sketchforge.exceptions import SketchForgeError
from sketchforge.orchestration.retry_policy import RetryPolicy
from sketchforge.orchestration.step_registry import StepRegistry
from sketchforge.orchestration.workflow_history import StepRecord
from sketchforge.orchestration.workflow_state import RunStatus, WorkflowState

ProgressFn = Callable[[str, int, int], None]  # (step name, index, total)
NO_RETRY = RetryPolicy(max_attempts=1)


class Workflow:
    def __init__(self, registry: StepRegistry, order: list[str],
                 retry: dict[str, RetryPolicy] | None = None) -> None:
        for name in order:
            registry.get(name)  # fail at construction if a step is missing
        self.registry, self.order, self.retry = registry, list(order), retry or {}

    def run(self, state: WorkflowState, on_progress: ProgressFn | None = None) -> WorkflowState:
        state.status = RunStatus.RUNNING
        total = len(self.order)
        for index, name in enumerate(self.order):
            if state.cancelled:
                state.history.add(StepRecord(name, "cancelled", 0.0))
                state.status = RunStatus.CANCELLED
                return state
            if on_progress:
                on_progress(name, index, total)
            fn = self.registry.get(name)
            policy = self.retry.get(name, NO_RETRY)
            t0 = time.perf_counter()
            try:
                detail = policy.run(lambda fn=fn: fn(state))
            except Exception as exc:  # a failing step must not crash the application
                ms = (time.perf_counter() - t0) * 1000
                label = str(exc) if isinstance(exc, SketchForgeError) else f"{type(exc).__name__}: {exc}"
                state.history.add(StepRecord(name, "failed", ms, label))
                state.status, state.failed_step, state.error = RunStatus.FAILED, name, label
                return state
            state.history.add(StepRecord(name, "ok", (time.perf_counter() - t0) * 1000, detail or ""))
        state.status = RunStatus.SUCCEEDED
        return state
