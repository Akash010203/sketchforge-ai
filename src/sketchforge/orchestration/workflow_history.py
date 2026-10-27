"""What happened in a workflow run, step by step."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StepRecord:
    name: str
    status: str  # 'ok' | 'failed' | 'skipped' | 'cancelled'
    duration_ms: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {"step": self.name, "status": self.status,
                "duration_ms": round(self.duration_ms, 2), "detail": self.detail}


@dataclass
class WorkflowHistory:
    steps: list[StepRecord] = field(default_factory=list)

    def add(self, record: StepRecord) -> None:
        self.steps.append(record)

    def total_ms(self) -> float:
        return sum(s.duration_ms for s in self.steps)

    def to_list(self) -> list[dict]:
        return [s.to_dict() for s in self.steps]
