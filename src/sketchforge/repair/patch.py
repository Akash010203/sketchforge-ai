"""A repair patch: a minimal, explainable set of property changes plus the record of its trial.

``Patch`` is the *proposal* (what would change and why). ``PatchRecord`` is what happened when it
was tried: the measurements before and after, the regression verdict and the final decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sketchforge.design_ir.schema import BBox, DesignDocument
from sketchforge.editor.design_commands import (
    Command,
    CompositeCommand,
    MoveCommand,
    SetBBoxCommand,
    SetStyleCommand,
    SetTypographyCommand,
)
from sketchforge.exceptions import RepairError


@dataclass(frozen=True)
class PropertyChange:
    """One property of one component.

    ``property`` is ``position`` (moves the component *and its descendants*), ``bbox`` (resizes only
    this component), ``style.<field>`` or ``typography.<field>``.
    """

    component_id: str
    property: str
    original: Any
    proposed: Any

    def to_command(self, reason: str) -> Command:
        cid, prop = self.component_id, self.property
        if prop == "position":
            return MoveCommand(
                cid, self.proposed["x"] - self.original["x"], self.proposed["y"] - self.original["y"],
                reason=reason,
            )
        if prop == "bbox":
            return SetBBoxCommand(cid, BBox(**self.proposed), reason=reason)
        if prop.startswith("style."):
            return SetStyleCommand(cid, **{prop.split(".", 1)[1]: self.proposed})
        if prop.startswith("typography."):
            return SetTypographyCommand(cid, **{prop.split(".", 1)[1]: self.proposed})
        raise RepairError(f"unsupported patch property {prop!r}")

    def to_dict(self) -> dict:
        return {"component": self.component_id, "property": self.property,
                "original": self.original, "proposed": self.proposed}


@dataclass(frozen=True)
class Patch:
    issue_key: str
    issue_code: str
    strategy: str
    changes: tuple[PropertyChange, ...]
    reason: str
    expected: str  # human-readable expected improvement
    expected_target_after: float = 0.0  # the target issue measure we expect afterwards
    variant: str = ""  # which candidate of the strategy this is (e.g. "aligned" / "minimal")

    @property
    def candidate_id(self) -> str:
        return f"{self.strategy}:{self.variant}"

    @property
    def component_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c.component_id for c in self.changes))

    def to_command(self, doc: DesignDocument | None = None) -> CompositeCommand:
        cmds = [c.to_command(self.reason) for c in self.changes]
        return CompositeCommand(cmds, f"repair {self.issue_key} via {self.strategy}")

    def to_dict(self) -> dict:
        return {
            "issue": self.issue_key, "strategy": self.strategy, "variant": self.variant,
            "reason": self.reason,
            "expected": self.expected, "changes": [c.to_dict() for c in self.changes],
        }


@dataclass
class PatchRecord:
    patch: Patch
    decision: str  # 'accepted' | 'rejected'
    reason: str
    target_before: float
    target_after: float | None
    regression: dict[str, Any] = field(default_factory=dict)
    metrics_before: dict[str, float] = field(default_factory=dict)
    metrics_after: dict[str, float] = field(default_factory=dict)
    visual: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0
    iteration: int = 0

    @property
    def accepted(self) -> bool:
        return self.decision == "accepted"

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration, "decision": self.decision, "reason": self.reason,
            "patch": self.patch.to_dict(), "target_before": round(self.target_before, 4),
            "target_after": None if self.target_after is None else round(self.target_after, 4),
            "regression": self.regression, "visual": {k: round(v, 5) for k, v in self.visual.items()},
            "metrics_before": {k: round(v, 4) for k, v in self.metrics_before.items()},
            "metrics_after": {k: round(v, 4) for k, v in self.metrics_after.items()},
            "duration_ms": round(self.duration_ms, 2),
        }
