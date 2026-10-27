"""Decide whether a trial patch may be kept.

A patch is accepted only if all of these hold:

1. the *target* issue improved by at least ``min_target_improvement`` (or disappeared);
2. no issue appeared that was not there before;
3. no existing issue got larger (beyond a 0.5 tolerance);
4. mean IoU against the sketch detections did not fall by more than ``max_fidelity_iou_drop``;
5. mean position error against the detections did not grow by more than
   ``max_position_error_increase_px``.

Checks 4-5 are skipped for documents without sketch provenance and say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sketchforge.design_ir.constraints import RegressionPolicy
from sketchforge.evaluation.evaluator import EvaluationResult
from sketchforge.repair.patch import Patch

WORSENED_TOLERANCE = 0.5


@dataclass
class RegressionResult:
    passed: bool
    target_before: float
    target_after: float
    improvement: float
    new_issues: list[str] = field(default_factory=list)
    continued: list[str] = field(default_factory=list)
    worsened: list[dict] = field(default_factory=list)
    fidelity_iou_drop: float | None = None
    position_error_increase_px: float | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed, "target_before": round(self.target_before, 4),
            "target_after": round(self.target_after, 4), "improvement": round(self.improvement, 4),
            "new_issues": list(self.new_issues), "continued": list(self.continued), "worsened": list(self.worsened),
            "fidelity_iou_drop": None if self.fidelity_iou_drop is None else round(self.fidelity_iou_drop, 5),
            "position_error_increase_px": None if self.position_error_increase_px is None
            else round(self.position_error_increase_px, 4),
            "reasons": list(self.reasons),
        }


def target_measure(result: EvaluationResult, issue_key: str) -> float:
    found = result.issue(issue_key)
    return found.measure if found is not None else 0.0


def check_regression(
    before: EvaluationResult,
    after: EvaluationResult,
    patch: Patch,
    policy: RegressionPolicy,
) -> RegressionResult:
    t_before = target_measure(before, patch.issue_key)
    t_after = target_measure(after, patch.issue_key)
    improvement = t_before - t_after
    reasons: list[str] = []

    if improvement < policy.min_target_improvement:
        reasons.append(
            f"target {patch.issue_key} did not improve enough "
            f"({t_before:.3f} -> {t_after:.3f}, needs >= {policy.min_target_improvement})"
        )

    new_keys, continued, worsened = [], [], []
    vanished = {k for k in before.keys() - after.keys() if k != patch.issue_key}
    claimed: set[str] = set()
    for key in sorted(after.keys() - before.keys()):
        later = after.issue(key)
        # An issue whose identity changed because its group changed (for example a repeated group
        # that gained or lost a member) is the *continuation* of an issue that vanished, not a new one.
        old = next((before.issue(k) for k in sorted(vanished - claimed)
                    if before.issue(k).code == later.code
                    and set(before.issue(k).component_ids) & set(later.component_ids)), None)
        if old is None:
            new_keys.append(key)
            continue
        claimed.add(old.key)
        continued.append(f"{old.key} -> {key}")
        if later.measure > old.measure + WORSENED_TOLERANCE:
            worsened.append({"issue": key, "before": round(old.measure, 3), "after": round(later.measure, 3)})
    if new_keys:
        reasons.append(f"introduced {len(new_keys)} new issue(s): {', '.join(new_keys[:4])}")

    for key in sorted(before.keys() & after.keys()):
        if key == patch.issue_key:
            continue
        b, a = before.issue(key).measure, after.issue(key).measure
        if a > b + WORSENED_TOLERANCE:
            worsened.append({"issue": key, "before": round(b, 3), "after": round(a, 3)})
    if worsened:
        reasons.append(f"made {len(worsened)} existing issue(s) worse: {worsened[0]['issue']}")

    iou_drop = pos_increase = None
    skipped = False
    if before.fidelity is not None and after.fidelity is not None:
        iou_drop = before.fidelity.mean_iou - after.fidelity.mean_iou
        pos_increase = after.fidelity.mean_position_error_px - before.fidelity.mean_position_error_px
        if iou_drop > policy.max_fidelity_iou_drop:
            reasons.append(f"fidelity IoU fell by {iou_drop:.3f} (limit {policy.max_fidelity_iou_drop})")
        if pos_increase > policy.max_position_error_increase_px:
            reasons.append(
                f"mean position error grew by {pos_increase:.2f}px "
                f"(limit {policy.max_position_error_increase_px})"
            )
    else:
        skipped = True  # recorded, but not a failure
    passed = not reasons
    if passed:
        reasons = ["all regression checks passed"]
        if skipped:
            reasons.append("fidelity checks skipped (no sketch provenance)")
        if continued:
            reasons.append(f"regrouped issues not counted as new: {'; '.join(continued)}")
    return RegressionResult(
        passed, t_before, t_after, improvement, new_keys, continued, worsened, iou_drop, pos_increase,
        reasons,
    )
