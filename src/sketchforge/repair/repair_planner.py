"""Choose which issue to repair next and which strategy to try for it."""

from __future__ import annotations

from dataclasses import dataclass

from typing import Any

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.evaluator import EvaluationResult
from sketchforge.evaluation.issues import Issue
from sketchforge.repair.diagnosis import Diagnosis, diagnose
from sketchforge.repair.patch import Patch
from sketchforge.repair.repair_rules import RULES

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}
# Coarse to fine: fix what defines the geometry (containment, overlap, size) before fine
# alignment and spacing, and appearance last. Fine adjustments made on top of broken geometry
# tend to be undone or contradicted by the geometry fix.
_CODE_RANK = {
    I.OVERFLOW_PAGE: 0, I.OVERFLOW_PARENT: 0, I.OVERLAP: 1, I.TEXT_CLIPPED: 2, I.TEXT_OVERFLOW: 2,
    I.TOUCH_TARGET_SMALL: 2, I.MISALIGNED: 3, I.UNEVEN_SPACING: 4, I.LOW_CONTRAST: 5,
    I.FONT_TOO_SMALL: 5,
}


@dataclass
class Plan:
    issue: Issue
    diagnosis: Diagnosis
    patch: Patch


def priority(issue: Issue) -> tuple:
    """Errors first, then coarse-to-fine by kind, then larger problems first; ties by key so the
    order is stable."""
    return (_SEVERITY_RANK[issue.severity], _CODE_RANK.get(issue.code, 9), -issue.measure, issue.key)


def next_plan(
    doc: DesignDocument,
    evaluation: EvaluationResult,
    constraints: LayoutConstraints,
    tried: dict[str, list[str]],
    max_attempts: int,
    *,
    only_codes: set[str] | None = None,
    only_keys: set[str] | None = None,
    model_provider: Any = None,
) -> tuple[Plan | None, list[str]]:
    """The highest-priority repairable issue and its next untried candidate patch.

    ``tried`` maps issue key -> candidate ids (``strategy:variant``) already attempted. Returns
    ``(plan, notes)``; ``plan`` is None when nothing is left to try. ``notes`` explains skipped
    issues. Only actual attempts count toward ``max_attempts``. ``only_codes`` / ``only_keys`` restrict
    which issues may be targeted (by code, by exact issue key); both must match when both are given.
    """
    notes: list[str] = []
    for issue in sorted(evaluation.issues, key=priority):
        if only_codes is not None and issue.code not in only_codes:
            continue
        if only_keys is not None and issue.key not in only_keys:
            continue
        done = tried.get(issue.key, [])
        if len(done) >= max_attempts:
            notes.append(f"{issue.key}: gave up after {len(done)} attempts ({', '.join(done)})")
            continue
        diag = diagnose(doc, issue, constraints)
        # When a provider is explicitly configured, let it propose first. Its patch goes through
        # the same edit validation, render/evaluation, and regression gate as every local rule;
        # rejected or unavailable proposals fall through to deterministic candidates.
        if model_provider is not None and "model_proposal:single" not in done:
            from sketchforge.assist.model_proposer import propose_repair
            proposed = propose_repair(model_provider, doc, issue)
            if proposed.patch is not None:
                return Plan(issue, diag, proposed.patch), notes
            notes.append(f"{issue.key}: {proposed.reason}")
        applicable = False
        for strategy in diag.strategies:
            candidates = RULES[strategy](doc, issue, constraints)
            if not candidates:
                notes.append(f"{issue.key}: strategy {strategy} not applicable")
                continue
            for patch in candidates:
                applicable = True
                if patch.candidate_id not in done:
                    return Plan(issue, diag, patch), notes
        if not applicable:
            notes.append(f"{issue.key}: no applicable repair")
    return None, notes
