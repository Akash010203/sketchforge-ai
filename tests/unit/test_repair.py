import pytest

from sketchforge.bootstrap import WorkflowConfig
from sketchforge.design_ir import (
    LayoutConstraints,
    RegressionPolicy,
    document_hash,
    validate_document,
)
from sketchforge.editor import SetTextCommand, UndoStack
from sketchforge.evaluation import evaluate_document
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.report import Outcome
from sketchforge.exceptions import RepairError
from sketchforge.orchestration.repair_workflow import run_repair, try_patch
from sketchforge.repair.diagnosis import diagnose
from sketchforge.repair.error_injection import KINDS, inject
from sketchforge.repair.issue_detector import detect
from sketchforge.repair.patch import Patch, PropertyChange
from sketchforge.repair.regression_check import check_regression
from sketchforge.repair.repair_planner import next_plan
from sketchforge.repair.rollback import RollbackPoint
from support import make_form_document

C, P = LayoutConstraints(), RegressionPolicy()


@pytest.fixture
def doc():
    return make_form_document()


def injected(doc, kind):
    stack = UndoStack(doc)
    rec = inject(doc, kind, stack)
    return stack, rec


@pytest.mark.parametrize("kind", KINDS)
def test_each_injection_is_detected_then_fully_repaired(doc, kind):
    assert evaluate_document(doc, C).issues == []
    stack, rec = injected(doc, kind)
    before = evaluate_document(doc, C)
    assert rec.expected_code in {i.code for i in before.issues}, [i.key for i in before.issues]

    report = run_repair(doc, stack=stack, injection=rec.to_dict())
    assert report.outcome is Outcome.IMPROVED, report.to_markdown()
    assert report.final.issues == [], [i.key for i in report.final.issues]
    assert report.accepted, "at least one patch must have been accepted"
    assert validate_document(doc).ok
    # every accepted patch targeted something that was really there
    for r in report.accepted:
        assert r.target_before > 0 and r.target_after < r.target_before
    # the repair is minimal: the fixed document is not wildly different from the clean one
    changed = sum(1 for a, b in zip(make_form_document().components, doc.components, strict=True) if a != b)
    assert changed <= 3, f"{kind}: repair touched {changed} components"


def test_overflow_repair_is_a_single_minimal_translation(doc):
    stack, rec = injected(doc, "overflow")
    report = run_repair(doc, stack=stack)
    (accepted,) = report.accepted
    (change,) = accepted.patch.changes
    assert change.property == "position" and change.component_id == rec.component_ids[0]
    assert accepted.patch.strategy == "translate_into_container"
    assert doc.require("button-1").bbox.x2 <= doc.require("card-1").bbox.x2
    assert accepted.visual["changed_pixel_ratio"] < 0.1


def test_clean_document_needs_no_repair(doc):
    report = run_repair(doc)
    assert report.outcome is Outcome.NO_MEASURABLE_DIFFERENCE
    assert report.records == [] and report.stop_reason == "no issues to repair"
    assert report.hash_before == report.hash_after


def test_regressing_patch_is_rejected_and_rolled_back_exactly(doc):
    stack, _ = injected(doc, "misalignment")
    before_eval = evaluate_document(doc, C)
    issue = before_eval.by_code(I.MISALIGNED)[0]
    # A deliberately bad patch: "fixes" the misalignment by launching the input into another one.
    victim = issue.component_ids[0]
    box = doc.require(victim).bbox
    bad = Patch(
        issue.key, issue.code, "bad_test_strategy",
        (PropertyChange(victim, "position", {"x": box.x, "y": box.y}, {"x": 130.0, "y": box.y - 60.0}),),
        "test", "n/a",
    )
    plan = type("P", (), {"patch": bad, "issue": issue})()
    from sketchforge.rendering.render_snapshot import render_image

    h = document_hash(doc)
    rec, after, _ = try_patch(doc, stack, plan, before_eval, render_image(doc), C, P, 1)
    assert rec.decision == "rejected" and after is None
    assert "new issue" in rec.reason or "worse" in rec.reason
    assert document_hash(doc) == h, "a rejected patch must leave the document byte-identical"


def test_patch_that_does_not_improve_the_target_is_rejected(doc):
    stack, _ = injected(doc, "overflow")
    ev = evaluate_document(doc, C)
    issue = ev.issues[0]
    noop = Patch(issue.key, issue.code, "noop", (
        PropertyChange("heading-1", "style.opacity", 1.0, 0.9),), "does nothing useful", "n/a")
    plan = type("P", (), {"patch": noop, "issue": issue})()
    from sketchforge.rendering.render_snapshot import render_image

    rec, _, _ = try_patch(doc, stack, plan, ev, render_image(doc), C, P, 1)
    assert rec.decision == "rejected" and "did not improve" in rec.reason


def test_locked_component_is_not_modified(doc):
    stack, rec = injected(doc, "overflow")
    victim = rec.component_ids[0]
    doc.require(victim).locked = True
    outcome = detect(doc, C)
    assert outcome.blocked and not [i for i in outcome.repairable if victim in i.component_ids]
    h = document_hash(doc)
    report = run_repair(doc, stack=stack)
    assert all(not r.accepted for r in report.records)
    assert all("locked" in r.reason for r in report.records)
    assert document_hash(doc) == h


def test_attempts_per_failure_are_capped_at_three(doc):
    stack, rec = injected(doc, "overflow")
    doc.require(rec.component_ids[0]).locked = True
    report = run_repair(doc, stack=stack, limits=WorkflowConfig(max_repair_iterations=20, no_progress_window=20))
    per_issue = {}
    for r in report.records:
        per_issue[r.patch.issue_key] = per_issue.get(r.patch.issue_key, 0) + 1
    assert per_issue and max(per_issue.values()) <= 3


def test_iteration_limit_and_no_progress_rule(doc):
    for kind in ("overflow", "misalignment", "spacing"):
        inject(doc, kind, UndoStack(doc))
    limited = run_repair(doc, limits=WorkflowConfig(max_repair_iterations=1))
    assert len(limited.records) == 1 and "iteration limit" in limited.stop_reason


def test_time_budget_stops_the_loop(doc):
    stack, _ = injected(doc, "overflow")
    report = run_repair(doc, stack=stack, limits=WorkflowConfig(repair_time_budget_seconds=1e-9))
    assert report.records == [] and "time budget" in report.stop_reason


def test_cancellation(doc):
    stack, _ = injected(doc, "overflow")
    report = run_repair(doc, stack=stack, cancelled=lambda: True)
    assert report.stop_reason == "cancelled" and report.records == []


def test_multiple_faults_are_repaired_in_priority_order(doc):
    stack = UndoStack(doc)
    for kind in ("overflow", "misalignment", "low_contrast"):
        inject(doc, kind, stack)
    report = run_repair(doc, stack=stack)
    assert report.outcome is Outcome.IMPROVED and report.final.issues == []
    first = report.records[0].patch.issue_code
    assert first == I.OVERFLOW_PARENT, "errors are repaired before warnings"


def test_diagnosis_picks_strategy_by_cause(doc):
    UndoStack(doc).execute(SetTextCommand("button-1", "Submit " * 12))
    ev = evaluate_document(doc, C)
    d = diagnose(doc, ev.by_code(I.TEXT_OVERFLOW)[0], C)
    assert d.strategies[0] == "widen_box"  # far too long: shrinking a little would not help
    doc2 = make_form_document()
    UndoStack(doc2).execute(SetTextCommand("button-1", "Submit your application now please, thanks"))
    d2 = diagnose(doc2, evaluate_document(doc2, C).by_code(I.TEXT_OVERFLOW)[0], C)
    assert d2.strategies[0] == "shrink_font"


def test_regression_check_reports_each_reason(doc):
    stack, _ = injected(doc, "overflow")
    before = evaluate_document(doc, C)
    issue = before.issues[0]
    patch = Patch(issue.key, issue.code, "x", (), "r", "e")
    same = check_regression(before, before, patch, P)
    assert not same.passed and "did not improve" in same.reasons[0]


def test_planner_skips_exhausted_issues(doc):
    stack, _ = injected(doc, "overflow")
    ev = evaluate_document(doc, C)
    key = ev.issues[0].key
    plan, _ = next_plan(doc, ev, C, {}, 3)
    assert plan is not None and plan.issue.key == key
    plan2, notes = next_plan(doc, ev, C, {key: ["a", "b", "c"]}, 3)
    assert plan2 is None


def test_rollback_point_verifies_restoration(doc):
    point = RollbackPoint(doc)
    UndoStack(doc).execute(SetTextCommand("heading-1", "changed"))
    assert not point.matches(doc)
    point.restore(doc)
    assert point.matches(doc) and doc.require("heading-1").text == "Sign up"


def test_report_serialises(doc, tmp_path):
    stack, rec = injected(doc, "spacing")
    report = run_repair(doc, stack=stack, injection=rec.to_dict())
    paths = report.save(tmp_path)
    import json

    data = json.loads(paths["json"].read_text())
    assert data["outcome"] == "IMPROVED" and data["attempts"] and data["injection"]["kind"] == "spacing"
    md = paths["markdown"].read_text()
    assert "## Attempts" in md and "accepted" in md.lower()
    assert paths["comparison"].exists()


def test_unknown_injection_kind(doc):
    with pytest.raises(RepairError):
        inject(doc, "nonsense")


def test_unfixable_overflow_is_reported_not_papered_over(doc):
    """Text 4x too long for any input: no geometry/typography change fits it, so the engine must
    leave the document alone and say so, rather than shrink the font to an unreadable size."""
    stack = UndoStack(doc)
    stack.execute(SetTextCommand("input-1", "very long placeholder " * 10))
    h = document_hash(doc)
    report = run_repair(doc, stack=stack)
    assert document_hash(doc) == h and not report.accepted
    assert [i.code for i in report.final.issues] == [I.TEXT_OVERFLOW]
    assert report.outcome is Outcome.NO_MEASURABLE_DIFFERENCE
    assert "no applicable strategy" in report.stop_reason
