"""Named workflow steps."""

from __future__ import annotations

from collections.abc import Callable

from sketchforge.exceptions import WorkflowError
from sketchforge.orchestration.workflow_state import WorkflowState

StepFn = Callable[[WorkflowState], str | None]


class StepRegistry:
    def __init__(self) -> None:
        self._steps: dict[str, StepFn] = {}

    def register(self, name: str) -> Callable[[StepFn], StepFn]:
        def decorator(fn: StepFn) -> StepFn:
            if name in self._steps:
                raise WorkflowError(f"step {name!r} is already registered")
            self._steps[name] = fn
            return fn
        return decorator

    def get(self, name: str) -> StepFn:
        try:
            return self._steps[name]
        except KeyError as exc:
            raise WorkflowError(f"unknown workflow step {name!r}") from exc

    def names(self) -> list[str]:
        return list(self._steps)
