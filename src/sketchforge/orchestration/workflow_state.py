"""Explicit, inspectable workflow state."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sketchforge.orchestration.workflow_history import WorkflowHistory


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowState:
    """Shared context for the steps of one run. Steps read and write ``context`` by key."""

    context: dict[str, Any] = field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    failed_step: str | None = None
    error: str | None = None
    history: WorkflowHistory = field(default_factory=WorkflowHistory)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def require(self, key: str) -> Any:
        if key not in self.context:
            raise KeyError(f"workflow context has no {key!r}; an earlier step did not produce it")
        return self.context[key]
