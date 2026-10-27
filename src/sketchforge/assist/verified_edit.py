"""Apply an edit plan, measure it, and repair what it broke: the closed loop around any planner.

A plan is only ever a proposal. ``apply_plan`` works on a *copy* of the document:

    validate -> execute on the copy -> evaluate -> (new problems?) -> bounded repair of only those
    problems -> re-evaluate -> classify

and returns an :class:`EditResult` that says exactly what happened. The caller's document is never
touched; the controller applies ``result.document`` as one undoable step if it chooses to. The
statuses are deliberately distinct:

``rejected``            validation or execution failed; nothing changed
``applied_clean``       applied; the edit introduced no new problem
``applied_repaired``    applied; the edit introduced problems and the bounded repair fixed all of them
``applied_with_issues`` applied; some introduced problems remain (repair off, exhausted, or unable)
``rolled_back``         ``rollback_on_unresolved`` was set and problems remained; nothing changed
``unable_to_verify``    the evaluation itself failed, so nothing was applied
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sketchforge.assist.edit_plan import EditPlan, InvalidPlan, PlanCommand, validate_plan
from sketchforge.bootstrap import WorkflowConfig
from sketchforge.design_ir.constraints import LayoutConstraints, RegressionPolicy
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import document_hash, from_dict
from sketchforge.editor.undo_redo import UndoStack
from sketchforge.evaluation.evaluator import EvaluationResult, evaluate_document
from sketchforge.evaluation.report import RepairReport
from sketchforge.exceptions import SketchForgeError
from sketchforge.orchestration.repair_workflow import run_repair

WORSENED_BY_PX = 0.5  # an existing issue counts as made worse by an edit beyond this much

APPLIED = ("applied_clean", "applied_repaired", "applied_with_issues")


@dataclass
class EditResult:
    status: str
    plan: EditPlan | None = None
    problems: list[str] = field(default_factory=list)
    before: EvaluationResult | None = None
    after_edit: EvaluationResult | None = None
    final: EvaluationResult | None = None
    introduced: list[str] = field(default_factory=list)   # issue keys the edit created or worsened
    unresolved: list[str] = field(default_factory=list)   # of those, still present at the end
    resolved_by_edit: list[str] = field(default_factory=list)  # pre-existing issues the edit fixed
    repair: RepairReport | None = None
    document: DesignDocument | None = None  # the candidate result (a copy); None unless applied
    hash_before: str = ""
    hash_after: str = ""
    duration_ms: float = 0.0

    @property
    def applied(self) -> bool:
        return self.status in APPLIED

    @property
    def changed_ids(self) -> set[str]:
        ids = set(self.plan.ops and {o.target for o in self.plan.ops} or ())
        if self.repair is not None:
            ids |= {cid for r in self.repair.accepted for cid in r.patch.component_ids}
        return ids

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "plan": self.plan.model_dump() if self.plan else None,
            "problems": self.problems,
            "introduced": self.introduced,
            "unresolved": self.unresolved,
            "resolved_by_edit": self.resolved_by_edit,
            "issues_before": int(self.before.metrics["issues_total"]) if self.before else None,
            "issues_after_edit": int(self.after_edit.metrics["issues_total"]) if self.after_edit else None,
            "issues_final": int(self.final.metrics["issues_total"]) if self.final else None,
            "repair_patches": len(self.repair.accepted) if self.repair else 0,
            "repair_outcome": self.repair.outcome.value if self.repair else None,
            "hash_before": self.hash_before, "hash_after": self.hash_after,
            "duration_ms": round(self.duration_ms, 1),
        }


def introduced_issues(before: EvaluationResult, after: EvaluationResult) -> tuple[set[str], set[str]]:
    """-> (keys the edit created or made worse, keys of pre-existing issues the edit resolved)."""
    bad: set[str] = set()
    for issue in after.issues:
        old = before.issue(issue.key)
        if old is None or issue.measure > old.measure + WORSENED_BY_PX:
            bad.add(issue.key)
    fixed = before.keys() - after.keys()
    return bad, fixed


def apply_plan(
    doc: DesignDocument,
    plan: EditPlan,
    *,
    constraints: LayoutConstraints | None = None,
    policy: RegressionPolicy | None = None,
    limits: WorkflowConfig | None = None,
    repair: bool = True,
    rollback_on_unresolved: bool = False,
) -> EditResult:
    constraints = constraints or LayoutConstraints()
    policy = policy or RegressionPolicy()
    limits = limits or WorkflowConfig()
    t0 = time.perf_counter()
    result = EditResult(status="rejected", plan=plan, hash_before=document_hash(doc))

    def done(status: str) -> EditResult:
        result.status = status
        result.duration_ms = (time.perf_counter() - t0) * 1000
        return result

    try:
        validate_plan(plan, doc)
    except InvalidPlan as exc:
        result.problems = list(exc.problems)
        return done("rejected")

    work = from_dict(doc.snapshot())
    stack = UndoStack(work)
    try:
        result.before = evaluate_document(work, constraints)
        stack.execute(PlanCommand(plan))
    except SketchForgeError as exc:  # EditError and friends: PlanCommand already undid any partial work
        result.problems = [str(exc)]
        return done("rejected")
    except Exception as exc:  # noqa: BLE001 - an unexpected failure must not leave a half-edited copy in play
        result.problems = [f"unexpected error while applying the plan: {exc}"]
        return done("unable_to_verify")

    try:
        result.after_edit = evaluate_document(work, constraints)
        bad, fixed = introduced_issues(result.before, result.after_edit)
        result.introduced = sorted(bad)
        result.resolved_by_edit = sorted(fixed)
        result.final = result.after_edit
        if bad and repair:
            result.repair = run_repair(work, constraints=constraints, policy=policy, limits=limits,
                                       stack=stack, only_keys=set(bad))
            result.final = evaluate_document(work, constraints)
        remaining = sorted(k for k in bad if _unresolved(k, result.before, result.final))
    except Exception as exc:  # noqa: BLE001
        result.problems = [f"could not verify the edit: {exc}"]
        return done("unable_to_verify")

    result.unresolved = remaining
    result.hash_after = document_hash(work)
    if remaining and rollback_on_unresolved:
        result.problems = [f"edit left {len(remaining)} unresolved problem(s); rolled back"]
        return done("rolled_back")
    result.document = work
    if not bad:
        return done("applied_clean")
    return done("applied_repaired" if not remaining else "applied_with_issues")


def _unresolved(key: str, before: EvaluationResult, final: EvaluationResult) -> bool:
    """An introduced issue is unresolved if it is still present and, when it already existed before the
    edit, still worse than it was then."""
    now = final.issue(key)
    if now is None:
        return False
    old = before.issue(key)
    return old is None or now.measure > old.measure + WORSENED_BY_PX
