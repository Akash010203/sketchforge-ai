"""The closed repair loop.

    evaluate -> plan -> apply -> re-render -> re-evaluate -> regression check -> accept | roll back

It is a *bounded* loop: an iteration limit, a time budget, at most ``max_attempts_per_failure``
tries per issue, and a no-progress rule. Every attempt, accepted or not, is recorded.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np

from sketchforge.bootstrap import WorkflowConfig
from sketchforge.design_ir.constraints import LayoutConstraints, RegressionPolicy
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import document_hash
from sketchforge.editor.undo_redo import UndoStack
from sketchforge.evaluation.evaluator import EvaluationResult, evaluate_document
from sketchforge.evaluation.image_metrics import changed_bbox, changed_pixel_ratio, ssim
from sketchforge.evaluation.report import Outcome, RepairReport, classify_outcome
from sketchforge.exceptions import EditError, RepairError
from sketchforge.integrations.provider_interface import ModelProvider
from sketchforge.orchestration.budget_manager import Budget
from sketchforge.orchestration.stopping_rules import StoppingRules
from sketchforge.rendering.render_snapshot import render_image
from sketchforge.repair.patch import PatchRecord
from sketchforge.repair.regression_check import check_regression
from sketchforge.repair.repair_planner import Plan, next_plan
from sketchforge.repair.rollback import RollbackPoint

EventFn = Callable[[str, dict], None]
RED, GREEN = (0, 0, 255), (60, 170, 40)


def _highlight(image: np.ndarray, doc: DesignDocument, ids: set[str], bgr: tuple[int, int, int]) -> np.ndarray:
    out = image.copy()
    for cid in ids:
        comp = doc.get(cid)
        if comp is not None and comp.id != doc.root_id:
            b = comp.bbox
            cv2.rectangle(out, (round(b.x) - 3, round(b.y) - 3), (round(b.x2) + 3, round(b.y2) + 3), bgr, 2)
    return out


def try_patch(
    doc: DesignDocument,
    stack: UndoStack,
    plan: Plan,
    before: EvaluationResult,
    before_image: np.ndarray,
    constraints: LayoutConstraints,
    policy: RegressionPolicy,
    iteration: int,
) -> tuple[PatchRecord, EvaluationResult | None, np.ndarray | None]:
    """Apply ``plan.patch`` tentatively. Returns (record, after_eval, after_image); the document is
    left in the patched state only if the record says accepted."""
    t0 = time.perf_counter()
    patch = plan.patch
    t_before = before.issue(patch.issue_key).measure if before.issue(patch.issue_key) else 0.0
    point = RollbackPoint(doc)

    def rejected(reason: str, **extra) -> PatchRecord:
        return PatchRecord(patch, "rejected", reason, t_before, extra.get("target_after"),
                           extra.get("regression", {}), extra.get("mb", {}), extra.get("ma", {}),
                           extra.get("visual", {}), (time.perf_counter() - t0) * 1000, iteration)

    try:
        stack.execute(patch.to_command(doc))
    except EditError as exc:
        if not point.matches(doc):
            point.restore(doc)
        return rejected(f"edit refused: {exc}"), None, None
    except Exception as exc:  # never leave a half-applied patch behind
        point.restore(doc)
        return rejected(f"unexpected {type(exc).__name__}: {exc}"), None, None

    after = evaluate_document(doc, constraints)
    after_image = render_image(doc)
    reg = check_regression(before, after, patch, policy)
    visual = {
        "changed_pixel_ratio": changed_pixel_ratio(before_image, after_image),
        "ssim": ssim(before_image, after_image),
    }
    box = changed_bbox(before_image, after_image)
    if box is not None:
        visual.update({"changed_x": box[0], "changed_y": box[1], "changed_w": box[2], "changed_h": box[3]})
    mb = {k: before.metrics[k] for k in ("issues_total", "issues_error")}
    ma = {k: after.metrics[k] for k in ("issues_total", "issues_error")}
    for k in ("fidelity_mean_iou", "position_error_mean_px"):
        if k in before.metrics and k in after.metrics:
            mb[k], ma[k] = before.metrics[k], after.metrics[k]

    if reg.passed:
        record = PatchRecord(patch, "accepted", "; ".join(reg.reasons), t_before, reg.target_after,
                             reg.to_dict(), mb, ma, visual, (time.perf_counter() - t0) * 1000, iteration)
        return record, after, after_image

    stack.undo()
    if not point.matches(doc):  # belt and braces: the undo must reproduce the exact prior state
        point.restore(doc)
    return rejected("; ".join(reg.reasons), target_after=reg.target_after, regression=reg.to_dict(),
                    visual=visual, mb=mb, ma=ma), None, None


def run_repair(
    doc: DesignDocument,
    *,
    constraints: LayoutConstraints | None = None,
    policy: RegressionPolicy | None = None,
    limits: WorkflowConfig | None = None,
    stack: UndoStack | None = None,
    injection: dict | None = None,
    only_codes: set[str] | None = None,
    only_keys: set[str] | None = None,
    on_event: EventFn | None = None,
    cancelled: Callable[[], bool] | None = None,
    model_provider: ModelProvider | None = None,
) -> RepairReport:
    """Repair ``doc`` in place and return the report. The document only ever holds accepted changes."""
    constraints = constraints or LayoutConstraints()
    policy = policy or RegressionPolicy()
    limits = limits or WorkflowConfig()
    stack = stack or UndoStack(doc)
    emit = on_event or (lambda *_: None)
    started = time.perf_counter()

    budget = Budget(limits.repair_time_budget_seconds, limits.max_repair_iterations)
    stopper = StoppingRules(limits.no_progress_window)
    hash_before = document_hash(doc)
    initial = evaluate_document(doc, constraints)
    initial_image = render_image(doc)
    current, current_image = initial, initial_image
    tried: dict[str, list[str]] = {}
    records: list[PatchRecord] = []
    notes: list[str] = []
    stop_reason = "no issues to repair"
    attempts = 0
    emit("evaluated", {"issues": int(initial.metrics["issues_total"])})

    while True:
        if cancelled and cancelled():
            stop_reason = "cancelled"
            break
        reason = budget.exhausted(attempts)
        if reason:
            stop_reason = reason
            break
        plan, plan_notes = next_plan(doc, current, constraints, tried, limits.max_attempts_per_failure,
                                     only_codes=only_codes, only_keys=only_keys,
                                     model_provider=model_provider)
        notes.extend(n for n in plan_notes if n not in notes)
        if plan is None:
            stop_reason = "no issues to repair" if not current.issues else "no applicable strategy left"
            break
        attempts += 1
        tried.setdefault(plan.issue.key, []).append(plan.patch.candidate_id)
        emit("attempt", {"iteration": attempts, "issue": plan.issue.key, "strategy": plan.patch.candidate_id})
        record, after, after_image = try_patch(doc, stack, plan, current, current_image, constraints,
                                               policy, attempts)
        records.append(record)
        emit("decision", {"iteration": attempts, "decision": record.decision, "reason": record.reason})
        stopper.record(record.accepted)
        if record.accepted:
            current, current_image = after, after_image
        else:
            stop = stopper.should_stop()
            if stop:
                stop_reason = stop
                break

    final = current
    hash_after = document_hash(doc)
    try:
        outcome = classify_outcome(initial, final)
        verified = evaluate_document(doc, constraints)  # independent re-measure of the saved state
        if verified.keys() != final.keys():
            raise RepairError("final evaluation does not match the tracked state")
    except Exception as exc:
        outcome = Outcome.UNABLE_TO_VERIFY
        notes.append(f"could not verify the final state: {exc}")
    if hash_before == hash_after and outcome is Outcome.IMPROVED:
        outcome = Outcome.NO_MEASURABLE_DIFFERENCE

    final_image = render_image(doc)
    touched = {cid for r in records if r.accepted for cid in r.patch.component_ids}
    images = {
        "before": _highlight(initial_image, doc, {cid for i in initial.issues for cid in i.component_ids}, RED),
        "after": _highlight(final_image, doc, touched, GREEN),
    }
    h = max(images["before"].shape[0], images["after"].shape[0])
    pad = lambda im: cv2.copyMakeBorder(im, 0, h - im.shape[0], 0, 12, cv2.BORDER_CONSTANT, value=(240, 240, 240))  # noqa: E731
    images["comparison"] = np.hstack([pad(images["before"]), pad(images["after"])])
    return RepairReport(
        outcome=outcome, initial=initial, final=final, records=records, stop_reason=stop_reason,
        hash_before=hash_before, hash_after=hash_after, injection=injection, notes=notes,
        limits={"max_iterations": limits.max_repair_iterations, "time_budget_s": limits.repair_time_budget_seconds,
                "max_attempts_per_failure": limits.max_attempts_per_failure,
                "no_progress_window": limits.no_progress_window},
        duration_ms=(time.perf_counter() - started) * 1000, images=images,
    )
