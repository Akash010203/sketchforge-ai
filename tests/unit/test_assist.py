"""The natural-language edit assistant: plan schema, summary privacy, local parser, model planner
(against a stub provider, no network) and the verified-edit loop."""

from __future__ import annotations

import json

import pytest

from sketchforge.assist.design_summary import SummaryPolicy, summarize_design, summary_json
from sketchforge.assist.edit_plan import (
    InvalidPlan,
    PlanCommand,
    parse_plan,
    resolve_color,
    validate_plan,
)
from sketchforge.assist.local_parser import parse_instruction
from sketchforge.assist.model_planner import PURPOSE, SYSTEM_PROMPT, extract_json, plan_with_model
from sketchforge.assist.verified_edit import apply_plan, introduced_issues
from sketchforge.design_ir import BBox, LayoutConstraints, document_hash
from sketchforge.editor import UndoStack
from sketchforge.evaluation import evaluate_document
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.exceptions import EditError
from sketchforge.integrations.provider_interface import (
    CompletionRequest,
    CompletionResult,
    HealthStatus,
    ModelProvider,
    PolicyViolation,
    ProviderRateLimited,
    Usage,
)
from sketchforge.repair.repair_planner import next_plan
from support import make_form_document

C = LayoutConstraints()


@pytest.fixture
def doc():
    return make_form_document()


def plan_of(*ops, explanation=""):
    return parse_plan({"ops": list(ops), "explanation": explanation})


class StubProvider:
    """A scripted provider: returns the queued replies in order and records every request."""

    name = "stub"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[CompletionRequest] = []
        self.log: list = []

    def complete(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return CompletionResult(text=reply, model="stub-model", usage=Usage(10, 5), latency_ms=12.0)

    def health(self):
        return HealthStatus(ok=True, provider="stub", detail="stub")

    @property
    def usage_log(self):
        return self.log


def test_stub_satisfies_provider_protocol():
    assert isinstance(StubProvider(), ModelProvider)


# --------------------------------------------------------------------------------- edit plan
def test_parse_plan_accepts_valid_and_rejects_unknown_things():
    ok = plan_of({"op": "set_fill", "target": "button-1", "color": "red"})
    assert ok.ops[0].op == "set_fill"
    for bad in (
        {"ops": [{"op": "delete", "target": "button-1"}]},                       # unknown op
        {"ops": [{"op": "set_fill", "target": "button-1", "color": "red", "x": 1}]},  # extra field
        {"ops": []},                                                             # empty
        {"ops": [{"op": "move", "target": "button-1", "dx": 5}] * 9},            # too many
        {"ops": [{"op": "set_fill", "target": "Button 1!", "color": "red"}]},    # bad id
        {"ops": [{"op": "grow", "target": "button-1", "dw": 1e9}]},              # out of range
        {"ops": [{"op": "set_fill", "target": "button-1", "color": "red"}], "x": 1},
    ):
        with pytest.raises(InvalidPlan):
            parse_plan(bad)


def test_resolve_color_names_and_hex():
    assert resolve_color("Light Blue") == "#bfdbfe"
    assert resolve_color("#ABC").lower() in ("#aabbcc", "#abc")
    with pytest.raises(EditError):
        resolve_color("not-a-colour")


def test_validate_plan_checks_the_live_document(doc):
    doc.require("heading-1").locked = True
    doc.require("input-1").editable = ["text"]
    plan = plan_of(
        {"op": "set_fill", "target": "ghost-9", "color": "red"},
        {"op": "set_text", "target": "heading-1", "text": "x"},
        {"op": "move", "target": "input-1", "dx": 5},
        {"op": "set_fill", "target": "page", "color": "red"},
        {"op": "set_text", "target": "card-1", "text": "x"},
        {"op": "set_fill", "target": "button-1", "color": "nonsense-colour"},
    )
    with pytest.raises(InvalidPlan) as err:
        validate_plan(plan, doc)
    text = " | ".join(err.value.problems)
    assert "no such component" in text and "locked" in text and "not editable" in text
    assert "page itself" in text and "does not carry text" in text and "op 6" in text


def test_plan_command_composes_ops_and_undoes_atomically(doc):
    before = document_hash(doc)
    stack = UndoStack(doc)
    plan = plan_of(
        {"op": "move", "target": "button-1", "dx": 10, "dy": 0},
        {"op": "resize", "target": "button-1", "width": 300},
        {"op": "set_text", "target": "button-1", "text": "Go"},
        {"op": "set_fill", "target": "button-1", "color": "red"},
    )
    stack.execute(PlanCommand(plan))
    b = doc.require("button-1")
    assert (b.bbox.x, b.bbox.w, b.text, b.style.fill) == (140, 300, "Go", "#dc2626")
    stack.undo()
    assert document_hash(doc) == before


def test_plan_command_failure_leaves_document_unchanged(doc):
    before = document_hash(doc)
    stack = UndoStack(doc)
    plan = plan_of(
        {"op": "set_fill", "target": "button-1", "color": "red"},
        {"op": "grow", "target": "button-1", "dh": -1000},  # would leave no height
    )
    with pytest.raises(EditError):
        stack.execute(PlanCommand(plan))
    assert document_hash(doc) == before and not stack.can_undo


# ------------------------------------------------------------------------------ design summary
def test_summary_hides_user_text_unless_opted_in(doc):
    doc.require("heading-1").text = "Quarterly secrets"          # user content (not inferred)
    doc.require("heading-1").name = "Secret heading"
    doc.require("button-1").text_is_inferred = True               # placeholder SketchForge made up
    s = summary_json(doc)
    assert "Quarterly secrets" not in s and "Secret heading" not in s
    assert "text_chars" in s and '"text":"Submit"' in s           # inferred text is shown
    assert "Quarterly secrets" in summary_json(doc, SummaryPolicy(include_user_text=True))


def test_summary_is_compact_deterministic_and_refuses_oversized_designs(doc):
    assert summary_json(doc) == summary_json(doc)
    data = summarize_design(doc)
    assert data["page"]["width"] == 600 and all(c["id"] != doc.root_id for c in data["components"])
    assert all(len(c["box"]) == 4 for c in data["components"])
    with pytest.raises(PolicyViolation):
        summarize_design(doc, SummaryPolicy(max_components=3))


# ------------------------------------------------------------------------------ local parser
@pytest.mark.parametrize("text, expect", [
    ("make the button red", [("set_fill", "button-1")]),
    ("change the button text to 'Go now'", [("set_text", "button-1")]),
    ("rename the heading to Welcome back", [("set_text", "heading-1")]),
    ("make the heading text blue", [("set_text_color", "heading-1")]),
    ("move the button down 20 px", [("move", "button-1")]),
    ("move button-1 to 100, 200", [("set_position", "button-1")]),
    ("center the button horizontally", [("set_position", "button-1")]),
    ("make the second field wider", [("grow", "input-2")]),
    ("make the last field 10 px taller", [("grow", "input-4")]),
    ("make the card 500 x 480", [("resize", "card-1")]),
    ("set the font size of the heading to 30", [("set_font_size", "heading-1")]),
    ("make the heading larger", [("set_font_size", "heading-1")]),
    ("round the corners of the button", [("set_corner_radius", "button-1")]),
    ("give the card a border", [("set_border", "card-1")]),
    ("make the button red and wider", [("set_fill", "button-1"), ("grow", "button-1")]),
    ("make the heading and the button green", [("set_text_color", "heading-1"), ("set_fill", "button-1")]),
    ("make the first field green then move it up 5", [("set_fill", "input-1"), ("move", "input-1")]),
    ("make the 'Submit' button red", [("set_fill", "button-1")]),
    ("make the text in the header white", [("set_text_color", "text-1")]),
])
def test_local_parser_understands(doc, text, expect):
    result = parse_instruction(text, doc)
    assert result.ok, (text, result.kind, result.reason)
    assert [(o.op, o.target) for o in result.plan.ops] == expect
    validate_plan(result.plan, doc)  # every plan the parser emits is valid for the document


@pytest.mark.parametrize("text, kind", [
    ("make the field red", "ambiguous"),            # four fields
    ("make the cancel button red", "no_target"),    # no such button
    ("make the 'Cancel' button red", "no_target"),
    ("make the checkbox red", "no_target"),         # none in this document
    ("delete the button", "unsupported"),
    ("move the button to the right", "unsupported"),  # no distance
    ("make it bigger", "no_target"),                 # nothing earlier to refer to
    ("blue", "no_target"),
    ("make the heading bold", "unparsed"),           # no such operation
    ("", "unparsed"),
    ("make the fifth field red", "no_target"),
])
def test_local_parser_refuses_rather_than_guesses(doc, text, kind):
    result = parse_instruction(text, doc)
    assert not result.ok and result.kind == kind and result.reason


def test_local_parser_never_picks_between_candidates(doc):
    result = parse_instruction("make the field wider", doc)
    assert result.plan is None and "input-1" in result.reason and "input-4" in result.reason


def test_local_parser_relative_amounts_follow_current_size(doc):
    plan = parse_instruction("make the button wider", doc).plan
    assert plan.ops[0].dw == pytest.approx(round(340 * 0.2))
    plan = parse_instruction("make the button 25 px narrower", doc).plan
    assert plan.ops[0].dw == -25


# ----------------------------------------------------------------------------- model planner
GOOD = json.dumps({"ops": [{"op": "set_fill", "target": "button-1", "color": "red"}], "explanation": "red"})


def test_extract_json_is_strict_but_tolerates_fence_and_think_blocks():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('<think>hmm</think>{"a": 1}') == {"a": 1}
    for bad in ("", "Sure! " + GOOD, GOOD + " done", "{'a': 1}", "[1, 2"):
        with pytest.raises(ValueError):
            extract_json(bad)


def test_planner_ok_and_request_shape(doc):
    provider = StubProvider(GOOD)
    out = plan_with_model(provider, doc, "make the button red")
    assert out.ok and out.kind == "ok" and out.attempts == 1 and out.plan.ops[0].target == "button-1"
    (request,) = provider.requests
    assert request.purpose == PURPOSE and request.json_mode and request.temperature == 0.0
    assert request.messages[0].role == "system" and request.messages[0].content == SYSTEM_PROMPT
    assert "make the button red" in request.messages[1].content and "button-1" in request.messages[1].content
    assert out.total_tokens == 15 and out.latency_ms == 12.0


def test_planner_retries_once_with_validator_feedback(doc):
    bad = json.dumps({"ops": [{"op": "set_fill", "target": "ghost-1", "color": "red"}]})
    provider = StubProvider(bad, GOOD)
    out = plan_with_model(provider, doc, "make the button red")
    assert out.ok and out.attempts == 2
    feedback = provider.requests[1].messages[-1].content
    assert "rejected" in feedback and "no such component" in feedback


def test_planner_gives_up_after_bounded_attempts(doc):
    bad = "I would make it red!"
    provider = StubProvider(bad, bad, GOOD)  # the third (good) reply must never be requested
    out = plan_with_model(provider, doc, "make the button red")
    assert out.kind == "invalid_plan" and out.plan is None and out.attempts == 2 and len(provider.replies) == 1


def test_planner_reports_refusal_without_retrying(doc):
    provider = StubProvider(json.dumps({"refusal": "several buttons match"}), GOOD)
    out = plan_with_model(provider, doc, "make it red")
    assert out.kind == "refused" and "several" in out.reason and len(provider.requests) == 1


def test_planner_returns_provider_errors_as_data(doc):
    out = plan_with_model(StubProvider(ProviderRateLimited("slow down", 3)), doc, "x")
    assert out.kind == "provider_error" and isinstance(out.error, ProviderRateLimited) and not out.ok


def test_planner_refuses_oversized_designs_before_sending_anything(doc):
    provider = StubProvider(GOOD)
    out = plan_with_model(provider, doc, "x", policy=SummaryPolicy(max_components=3))
    assert out.kind == "provider_error" and isinstance(out.error, PolicyViolation)
    assert provider.requests == []


def test_planner_never_includes_user_text_by_default(doc):
    doc.require("input-1").text = "jane@example.com"
    provider = StubProvider(GOOD)
    plan_with_model(provider, doc, "make the button red")
    sent = " ".join(m.content for m in provider.requests[0].messages)
    assert "jane@example.com" not in sent


# ------------------------------------------------------------------------------ verified edit
def test_clean_edit_is_applied_to_a_copy_only(doc):
    before = document_hash(doc)
    plan = plan_of({"op": "set_fill", "target": "button-1", "color": "red"})
    result = apply_plan(doc, plan, constraints=C)
    assert result.status == "applied_clean" and result.applied and result.introduced == []
    assert document_hash(doc) == before                      # the caller's document is untouched
    assert result.document.require("button-1").style.fill == "#dc2626"
    assert result.hash_after == document_hash(result.document) != before


def test_edit_that_breaks_layout_is_repaired_and_only_what_it_broke(doc):
    plan = plan_of({"op": "move", "target": "button-1", "dx": 60, "dy": 0})  # pokes out of the card
    result = apply_plan(doc, plan, constraints=C)
    assert result.introduced and any(k.startswith("OVERFLOW_PARENT") for k in result.introduced)
    assert result.status == "applied_repaired", (result.status, result.unresolved)
    assert result.repair is not None and result.repair.accepted
    assert result.unresolved == []
    assert evaluate_document(result.document, C).issues == []
    assert "button-1" in result.changed_ids


def test_repair_off_reports_applied_with_issues(doc):
    plan = plan_of({"op": "move", "target": "button-1", "dx": 60, "dy": 0})
    result = apply_plan(doc, plan, constraints=C, repair=False)
    assert result.status == "applied_with_issues" and result.unresolved and result.repair is None
    assert result.document is not None


def test_rollback_on_unresolved_applies_nothing(doc):
    plan = plan_of({"op": "move", "target": "button-1", "dx": 60, "dy": 0})
    result = apply_plan(doc, plan, constraints=C, repair=False, rollback_on_unresolved=True)
    assert result.status == "rolled_back" and result.document is None and not result.applied


def test_invalid_plan_is_rejected_without_touching_anything(doc):
    before = document_hash(doc)
    plan = plan_of({"op": "set_fill", "target": "ghost-1", "color": "red"})
    result = apply_plan(doc, plan, constraints=C)
    assert result.status == "rejected" and result.document is None and result.problems
    assert document_hash(doc) == before


def test_failing_operation_is_rejected_cleanly(doc):
    plan = plan_of({"op": "set_fill", "target": "button-1", "color": "red"},
                   {"op": "grow", "target": "button-1", "dh": -1000})
    result = apply_plan(doc, plan, constraints=C)
    assert result.status == "rejected" and "no size left" in result.problems[0] and result.document is None


def test_existing_problems_are_not_the_edits_responsibility(doc):
    doc.require("input-2").bbox = BBox(x=138, y=230, w=340, h=44)  # a pre-existing misalignment
    before = evaluate_document(doc, C)
    assert before.issues
    plan = plan_of({"op": "set_fill", "target": "button-1", "color": "red"})
    result = apply_plan(doc, plan, constraints=C)
    assert result.status == "applied_clean"
    assert result.final.keys() == before.keys()   # untouched: not silently "repaired" by a colour edit


def test_introduced_issues_detects_new_and_worsened_and_resolved(doc):
    base = evaluate_document(doc, C)
    stack = UndoStack(doc)
    from sketchforge.editor import SetBBoxCommand
    stack.execute(SetBBoxCommand("button-1", BBox(x=130, y=440, w=420, h=48)))  # 50 px past the card
    after = evaluate_document(doc, C)
    bad, fixed = introduced_issues(base, after)
    assert any(k.startswith("OVERFLOW_PARENT:button-1") for k in bad) and fixed == set()
    stack.undo()
    stack.execute(SetBBoxCommand("button-1", BBox(x=130, y=440, w=520, h=48)))  # worse
    worse = evaluate_document(doc, C)
    bad2, _ = introduced_issues(after, worse)
    assert any(k.startswith("OVERFLOW_PARENT:button-1") for k in bad2)
    stack.undo()
    bad3, fixed3 = introduced_issues(after, evaluate_document(doc, C))
    assert bad3 == set() and any(k.startswith("OVERFLOW_PARENT") for k in fixed3)


def test_repair_planner_only_keys_restricts_targets(doc):
    stack = UndoStack(doc)
    from sketchforge.editor import SetBBoxCommand
    stack.execute(SetBBoxCommand("button-1", BBox(x=130, y=440, w=420, h=48)))
    stack.execute(SetBBoxCommand("input-2", BBox(x=138, y=230, w=340, h=44)))
    ev = evaluate_document(doc, C)
    assert {i.code for i in ev.issues} >= {I.OVERFLOW_PARENT, I.MISALIGNED}
    key = next(i.key for i in ev.issues if i.code == I.MISALIGNED)
    plan, _ = next_plan(doc, ev, C, {}, 3, only_keys={key})
    assert plan is not None and plan.issue.key == key
    plan, _ = next_plan(doc, ev, C, {}, 3, only_keys={"NOPE:x:y"})
    assert plan is None


def test_repair_after_an_edit_touches_only_what_the_edit_broke(doc):
    doc.require("input-2").bbox = BBox(x=138, y=230, w=340, h=44)  # pre-existing misalignment
    pre = {i.key for i in evaluate_document(doc, C).issues}
    assert pre
    plan = plan_of({"op": "move", "target": "button-1", "dx": 60, "dy": 0})
    result = apply_plan(doc, plan, constraints=C)
    assert result.status == "applied_repaired"
    final = {i.key for i in result.final.issues}
    assert pre <= final, "a pre-existing problem was silently changed by the edit's repair"
    assert not any(k.startswith("OVERFLOW_PARENT") for k in final)
    assert all(r.patch.component_ids != ("input-2",) for r in result.repair.records)
