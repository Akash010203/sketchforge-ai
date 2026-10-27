"""A compact, privacy-aware description of a design: the only document content a model ever sees.

The summary carries ids, types, geometry and a few style facts. The *text inside* components is
user content: it is included only when the caller opts in (``SummaryPolicy.include_user_text``) or
when the text is a placeholder SketchForge itself inferred (``text_is_inferred``). Component names
are treated the same way. The sketch image is never part of a summary.

A design with more components than ``max_components`` is refused, not silently truncated: a model
that sees half a design would plan edits against a document that does not exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sketchforge.design_ir.schema import Component, ComponentType, DesignDocument
from sketchforge.integrations.provider_interface import PolicyViolation

TEXT_TYPES = {ComponentType.TEXT, ComponentType.HEADING, ComponentType.BUTTON, ComponentType.INPUT,
              ComponentType.CHECKBOX, ComponentType.RADIO}


@dataclass(frozen=True)
class SummaryPolicy:
    include_user_text: bool = False
    max_components: int = 120


def _shows_text(comp: Component, policy: SummaryPolicy) -> bool:
    return policy.include_user_text or comp.text_is_inferred


def _describe(comp: Component, policy: SummaryPolicy) -> dict:
    b = comp.bbox
    item: dict = {
        "id": comp.id, "type": comp.type.value,
        "box": [round(b.x), round(b.y), round(b.w), round(b.h)],
    }
    if comp.parent_id:
        item["parent"] = comp.parent_id
    if comp.style.fill not in ("transparent", "none"):
        item["fill"] = comp.style.fill
    if comp.style.stroke not in ("transparent", "none"):
        item["border"] = comp.style.stroke
    if comp.typography is not None and comp.type in TEXT_TYPES:
        item["text_color"] = comp.typography.color
        item["font_size"] = round(comp.typography.font_size)
    if comp.type in TEXT_TYPES:
        if comp.text and _shows_text(comp, policy):
            item["text"] = comp.text
        else:
            item["text_chars"] = len(comp.text or "")
    if comp.name and _shows_text(comp, policy):
        item["name"] = comp.name
    if comp.locked:
        item["locked"] = True
    if not comp.visible:
        item["hidden"] = True
    return item


def summarize_design(doc: DesignDocument, policy: SummaryPolicy | None = None) -> dict:
    """The summary as a plain dict. Raises :class:`PolicyViolation` for oversized designs."""
    policy = policy or SummaryPolicy()
    comps = [c for c in doc.components if c.id != doc.root_id]
    if len(comps) > policy.max_components:
        raise PolicyViolation(
            f"the design has {len(comps)} components; the limit for remote assistance is "
            f"{policy.max_components} (nebius.privacy.max_components). Edit locally or simplify the design.")
    return {
        "page": {"id": doc.root_id, "width": round(doc.page.width), "height": round(doc.page.height)},
        "components": [_describe(c, policy) for c in comps],
    }


def summary_json(doc: DesignDocument, policy: SummaryPolicy | None = None) -> str:
    """Deterministic, compact JSON of :func:`summarize_design`."""
    return json.dumps(summarize_design(doc, policy), separators=(",", ":"), sort_keys=True, ensure_ascii=False)
