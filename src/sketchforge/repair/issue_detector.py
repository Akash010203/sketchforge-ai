"""Find issues and say which of them the engine is allowed to repair."""

from __future__ import annotations

from dataclasses import dataclass

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.evaluation.evaluator import EvaluationResult, evaluate_document
from sketchforge.evaluation.issues import Issue


@dataclass
class DetectionOutcome:
    evaluation: EvaluationResult
    repairable: list[Issue]
    blocked: list[tuple[Issue, str]]  # (issue, why it will not be touched)


def detect(doc: DesignDocument, constraints: LayoutConstraints) -> DetectionOutcome:
    """Evaluate ``doc`` and split its issues into repairable and blocked (locked components)."""
    evaluation = evaluate_document(doc, constraints)
    repairable: list[Issue] = []
    blocked: list[tuple[Issue, str]] = []
    for issue in evaluation.issues:
        locked = [cid for cid in issue.component_ids if doc.require(cid).locked]
        if locked:
            blocked.append((issue, f"{', '.join(locked)} is locked"))
        else:
            repairable.append(issue)
    return DetectionOutcome(evaluation, repairable, blocked)
