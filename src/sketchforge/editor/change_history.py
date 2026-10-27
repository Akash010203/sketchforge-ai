"""A readable record of what changed, for the history panel and for reports."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChangeRecord:
    sequence: int
    kind: str  # 'do' | 'undo' | 'redo'
    description: str
    touched: tuple[str, ...]


@dataclass
class ChangeHistory:
    records: list[ChangeRecord] = field(default_factory=list)

    def add(self, kind: str, description: str, touched: set[str]) -> ChangeRecord:
        rec = ChangeRecord(len(self.records) + 1, kind, description, tuple(sorted(touched)))
        self.records.append(rec)
        return rec

    def descriptions(self) -> list[str]:
        return [f"{r.sequence}. [{r.kind}] {r.description}" for r in self.records]
