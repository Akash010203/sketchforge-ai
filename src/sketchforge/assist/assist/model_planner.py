"""The model planner: instruction + compact design summary -> validated :class:`EditPlan`.

The model is a *proposer*. Its output is parsed as strict JSON, checked against the plan schema and
then against the live document (``validate_plan``). Nothing in this module changes a document, and
a plan that fails either check is rejected with its reasons; at most one correction round is
attempted, with the validator's messages fed back. Provider failures are returned as data
(``kind="provider_error"``) so callers can fall back to the local parser instead of crashing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sketchforge.assist.design_summary import SummaryPolicy, summary_json
from sketchforge.assist.edit_plan import (
    COLOR_NAMES,
    MAX_OPS,
    EditPlan,
    InvalidPlan,
    parse_plan,
    validate_plan,
)
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.integrations.provider_interface import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderError,
)

PURPOSE = "nl_edit"
MAX_ATTEMPTS = 2

SYSTEM_PROMPT = f"""You translate one instruction about a UI design into a JSON edit plan.
You are given the design as JSON: the page size and a list of components. Each has an "id", a "type", a
"box" = [x, y, width, height] in page pixels (y grows downward), and sometimes "fill", "border",
"text_color", "font_size", "text" or "text_chars" (only the length of the text), "parent", "locked".

Reply with ONE JSON object and nothing else:
{{"ops": [ ... ], "explanation": "one short sentence"}}
or, if the instruction cannot be done with the operations below (or is ambiguous):
{{"refusal": "why, in one sentence"}}

Each op is an object with "op" and "target" (a component id taken from the design) plus these fields:
  set_text          text (string)
  set_fill          color
  set_text_color    color
  set_border        color
  move              dx, dy        (pixels, relative; +dx right, +dy down)
  set_position      x and/or y    (pixels, absolute page coordinates of the top-left corner)
  resize            width and/or height (pixels, absolute, > 0)
  grow              dw, dh        (pixels, relative change; negative shrinks)
  set_font_size     size          (pixels, 6..200)
  set_corner_radius radius        (pixels, >= 0)
"color" is a hex string like "#2563eb" or one of: {", ".join(sorted(COLOR_NAMES))}.

Rules:
- Use only ids that appear in the design. Never invent components. At most {MAX_OPS} ops.
- Change only what the instruction asks for. Do not move or resize anything else.
- "move" and "grow" are relative; "set_position" and "resize" are absolute.
- Moving a container moves everything inside it.
- If several components match an ambiguous description, refuse and say so.
- Do not wrap the JSON in markdown and do not add commentary.

Example design: {{"page":{{"id":"page","width":600,"height":400}},"components":[{{"id":"button-1","type":"button","box":[40,300,200,44],"fill":"#2563eb"}}]}}
Example instruction: make the button red and 20 px wider
Example reply: {{"ops":[{{"op":"set_fill","target":"button-1","color":"red"}},{{"op":"grow","target":"button-1","dw":20,"dh":0}}],"explanation":"Red fill and 20 px wider."}}"""


@dataclass
class PlannerOutcome:
    """What the model planner produced. ``kind`` is ``ok`` or one of ``refused`` / ``invalid_plan`` /
    ``provider_error`` / ``bad_output``."""

    kind: str
    plan: EditPlan | None = None
    reason: str | None = None
    attempts: int = 0
    results: list[CompletionResult] = field(default_factory=list)
    error: ProviderError | None = None

    @property
    def ok(self) -> bool:
        return self.plan is not None

    @property
    def latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results)

    @property
    def total_tokens(self) -> int:
        return sum(r.usage.total_tokens for r in self.results)


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> object:
    """Strictly decode the model's reply. Removes reasoning/think tags and markdown fences."""
    cleaned = _THINK.sub("", text or "").strip()
    cleaned = re.sub(r"<reasoning>.*?</reasoning>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    if not cleaned:
        raise ValueError("the reply was empty")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the reply was not a single JSON object ({exc.msg} at char {exc.pos})") from exc


def build_messages(doc: DesignDocument, instruction: str, policy: SummaryPolicy) -> tuple[ChatMessage, ...]:
    user = f"DESIGN:\n{summary_json(doc, policy)}\n\nINSTRUCTION:\n{instruction.strip()}"
    return (ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user))


def _check(raw: str, doc: DesignDocument) -> tuple[str, EditPlan | str]:
    """-> ("plan", plan) | ("refusal", why) | ("problems", message)."""
    try:
        data = extract_json(raw)
    except ValueError as exc:
        return "problems", str(exc)
    if isinstance(data, dict) and "refusal" in data and "ops" not in data:
        return "refusal", str(data.get("refusal") or "the model declined")[:300]
    try:
        plan = parse_plan(data)
        validate_plan(plan, doc)
    except InvalidPlan as exc:
        return "problems", "; ".join(exc.problems[:8])
    return "plan", plan


def plan_with_model(
    provider: ModelProvider,
    doc: DesignDocument,
    instruction: str,
    *,
    policy: SummaryPolicy | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    max_tokens: int = 2048,
    model: str | None = None,
) -> PlannerOutcome:
    """Ask ``provider`` for a plan. Never raises for provider or output problems."""
    policy = policy or SummaryPolicy()
    out = PlannerOutcome(kind="bad_output")
    try:
        messages = build_messages(doc, instruction, policy)
    except ProviderError as exc:  # oversized design: refused locally, nothing sent
        return PlannerOutcome(kind="provider_error", reason=str(exc), error=exc)
    last_problem = "no reply"
    for attempt in range(1, max(1, max_attempts) + 1):
        request = CompletionRequest(messages=messages, purpose=PURPOSE, max_tokens=max_tokens,
                                    temperature=0.0, json_mode=True, model=model)
        try:
            result = provider.complete(request)
        except ProviderError as exc:
            out.kind, out.reason, out.error, out.attempts = "provider_error", str(exc), exc, attempt
            return out
        out.results.append(result)
        out.attempts = attempt
        verdict, payload = _check(result.text, doc)
        if verdict == "plan":
            out.kind, out.plan, out.reason = "ok", payload, None  # type: ignore[assignment]
            return out
        if verdict == "refusal":
            out.kind, out.reason = "refused", str(payload)
            return out
        last_problem = str(payload)
        messages = (*messages, ChatMessage("assistant", result.text[:1500]),
                    ChatMessage("user", f"That reply was rejected: {last_problem}. "
                                        "Reply again with ONE corrected JSON object only."))
    out.kind = "invalid_plan"
    out.reason = f"the model's plan was rejected after {out.attempts} attempt(s): {last_problem}"
    return out
