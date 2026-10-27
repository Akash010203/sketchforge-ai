"""Optional model-assisted repair proposals, validated before entering the repair loop.

The provider only proposes property changes. The ordinary evaluator and regression gate remain
responsible for deciding whether any proposed change is applied permanently.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from sketchforge.assist.design_summary import SummaryPolicy, summary_json
from sketchforge.design_ir.schema import BBox, DesignDocument, Style, Typography
from sketchforge.evaluation.issues import Issue
from sketchforge.integrations.provider_interface import (
    ChatMessage,
    CompletionRequest,
    ModelProvider,
    ProviderError,
)
from sketchforge.repair.patch import Patch, PropertyChange

PURPOSE = "repair_proposal"
_STYLE_FIELDS = {"fill", "stroke", "stroke_width", "corner_radius", "opacity"}
_TYPOGRAPHY_FIELDS = {"font_size", "font_weight", "line_height", "text_align", "color"}
_SYSTEM = """Propose one minimal fix for the specified measurable UI layout issue.
Return exactly one JSON object: {"changes":[{"component":"id","property":"...","value":...}],"reason":"..."}.
Allowed properties are position (object {x,y}), bbox (object {x,y,w,h}), style.fill, style.stroke,
style.stroke_width, style.corner_radius, style.opacity, typography.font_size, typography.font_weight,
typography.line_height, typography.text_align, typography.color. Only change listed issue components.
Do not propose text edits or invent component ids. Keep the change minimal and target the issue.
"""


@dataclass(frozen=True)
class ProposalResult:
    patch: Patch | None
    reason: str


def propose_repair(provider: ModelProvider, doc: DesignDocument, issue: Issue) -> ProposalResult:
    """Ask once for a proposal and reject malformed, irrelevant, or invalid changes."""
    summary = summary_json(doc, SummaryPolicy(include_user_text=False))
    prompt = json.dumps({"design": json.loads(summary), "issue": issue.to_dict()},
                        separators=(",", ":"), ensure_ascii=False)
    request = CompletionRequest(
        messages=(ChatMessage("system", _SYSTEM), ChatMessage("user", prompt)),
        purpose=PURPOSE, max_tokens=500, temperature=0.0, json_mode=True,
    )
    try:
        response = provider.complete(request)
        raw = json.loads(response.text)
    except (ProviderError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return ProposalResult(None, f"model proposal unavailable: {exc}")
    if not isinstance(raw, dict) or set(raw) != {"changes", "reason"}:
        return ProposalResult(None, "model proposal has an unexpected shape")
    changes_raw, reason = raw["changes"], raw["reason"]
    if not isinstance(changes_raw, list) or not changes_raw or len(changes_raw) > 4:
        return ProposalResult(None, "model proposal must contain 1 to 4 changes")
    if not isinstance(reason, str) or not reason.strip():
        return ProposalResult(None, "model proposal did not explain its change")

    allowed_ids = set(issue.component_ids)
    changes: list[PropertyChange] = []
    seen: set[tuple[str, str]] = set()
    try:
        for item in changes_raw:
            if not isinstance(item, dict) or set(item) != {"component", "property", "value"}:
                raise ValueError("each change must contain component, property and value")
            cid, prop, value = item["component"], item["property"], item["value"]
            if not isinstance(cid, str) or not isinstance(prop, str):
                raise ValueError("component and property must be strings")
            if cid not in allowed_ids:
                raise ValueError("proposal targets a component outside the reported issue")
            comp = doc.get(cid)
            if comp is None or comp.locked:
                raise ValueError(f"component {cid!r} is missing or locked")
            if (cid, prop) in seen:
                raise ValueError("proposal changes one property more than once")
            seen.add((cid, prop))
            if prop == "position":
                if not isinstance(value, dict) or set(value) != {"x", "y"}:
                    raise ValueError("position must contain x and y")
                proposed = {k: float(value[k]) for k in ("x", "y")}
                if not all(math.isfinite(v) for v in proposed.values()):
                    raise ValueError("position values must be finite")
                original = {"x": comp.bbox.x, "y": comp.bbox.y}
            elif prop == "bbox":
                proposed = BBox.model_validate(value).model_dump()
                original = comp.bbox.model_dump()
            elif prop.startswith("style.") and prop.split(".", 1)[1] in _STYLE_FIELDS:
                field = prop.split(".", 1)[1]
                validated = Style.model_validate({**comp.style.model_dump(), field: value})
                proposed = getattr(validated, field)
                original = getattr(comp.style, field)
            elif prop.startswith("typography.") and prop.split(".", 1)[1] in _TYPOGRAPHY_FIELDS:
                if comp.typography is None:
                    raise ValueError(f"component {cid!r} has no typography")
                field = prop.split(".", 1)[1]
                validated = Typography.model_validate({**comp.typography.model_dump(), field: value})
                proposed = getattr(validated, field)
                original = getattr(comp.typography, field)
            else:
                raise ValueError(f"unsupported property {prop!r}")
            if proposed == original:
                raise ValueError("proposal contains a no-op change")
            changes.append(PropertyChange(cid, prop, original, proposed))
    except (TypeError, ValueError, KeyError) as exc:
        return ProposalResult(None, f"model proposal rejected: {exc}")

    patch = Patch(
        issue.key, issue.code, "model_proposal", tuple(changes), reason.strip()[:300],
        f"reduce {issue.code} on {', '.join(issue.component_ids)} (currently {issue.measure:g} {issue.unit})",
        variant="single",
    )
    return ProposalResult(patch, "model proposed a validated candidate")


__all__ = ["ProposalResult", "propose_repair"]
