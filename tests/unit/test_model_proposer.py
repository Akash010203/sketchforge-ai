import json
import pytest

from sketchforge.assist.model_proposer import propose_repair
from sketchforge.design_ir import LayoutConstraints
from sketchforge.editor import UndoStack
from sketchforge.evaluation import issues as I
from sketchforge.evaluation.issues import Issue
from sketchforge.integrations.provider_interface import (
    CompletionRequest,
    CompletionResult,
    HealthStatus,
    ProviderError,
    Usage,
)
from sketchforge.repair.error_injection import inject
from sketchforge.repair.repair_planner import next_plan
from support import make_form_document


class StubProvider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[CompletionRequest] = []

    def complete(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return CompletionResult(text=reply, model="stub-model", usage=Usage(10, 5), latency_ms=10.0)

    def health(self):
        return HealthStatus(ok=True, provider="stub", detail="stub")


def test_propose_repair_accepts_valid_position_change():
    doc = make_form_document()
    issue = Issue(
        code=I.OVERLAP,
        component_ids=("input-1", "input-2"),
        message="Inputs overlap",
        measure=10.0,
    )
    provider = StubProvider(
        json.dumps({
            "changes": [{"component": "input-2", "property": "position", "value": {"x": 130.0, "y": 250.0}}],
            "reason": "Move second input downwards to clear overlap",
        })
    )
    res = propose_repair(provider, doc, issue)
    assert res.patch is not None
    assert res.patch.strategy == "model_proposal"
    assert len(res.patch.changes) == 1
    assert res.patch.changes[0].component_id == "input-2"
    assert res.patch.changes[0].proposed == {"x": 130.0, "y": 250.0}


def test_propose_repair_rejects_provider_failure():
    doc = make_form_document()
    issue = Issue(
        code=I.OVERLAP,
        component_ids=("input-1",),
        message="Issue",
        measure=1.0,
    )
    provider = StubProvider(ProviderError("Network unreachable"))
    res = propose_repair(provider, doc, issue)
    assert res.patch is None
    assert "model proposal unavailable" in res.reason


def test_propose_repair_rejects_unrelated_or_locked_component():
    doc = make_form_document()
    doc.get("button-1").locked = True
    issue = Issue(
        code=I.OVERLAP,
        component_ids=("input-1",),
        message="Issue",
        measure=1.0,
    )
    # targeting button-1 which is not in issue.component_ids
    provider = StubProvider(
        json.dumps({
            "changes": [{"component": "button-1", "property": "position", "value": {"x": 10.0, "y": 10.0}}],
            "reason": "Move button",
        })
    )
    res = propose_repair(provider, doc, issue)
    assert res.patch is None
    assert "outside the reported issue" in res.reason


def test_next_plan_uses_model_provider_proposal():
    doc = make_form_document()
    stack = UndoStack(doc)
    inject(doc, "overlap", stack)
    from sketchforge.evaluation.evaluator import evaluate_document
    evaluation = evaluate_document(doc)
    assert len(evaluation.issues) > 0

    target_issue = evaluation.issues[0]
    cid = target_issue.component_ids[0]
    comp = doc.get(cid)
    provider = StubProvider(
        json.dumps({
            "changes": [{"component": cid, "property": "position", "value": {"x": comp.bbox.x + 5.0, "y": comp.bbox.y + 5.0}}],
            "reason": "Nudge component",
        })
    )
    plan, notes = next_plan(doc, evaluation, LayoutConstraints(), tried={}, max_attempts=3, model_provider=provider)
    assert plan is not None
