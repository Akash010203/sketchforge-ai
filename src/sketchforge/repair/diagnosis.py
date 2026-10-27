"""Diagnosis: why does this issue exist, and which repair strategies are worth trying, in order."""

from __future__ import annotations

from dataclasses import dataclass, field

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.schema import BBox, DesignDocument
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.issues import Issue

# strategy names (implemented in repair_rules.py)
TRANSLATE_INTO = "translate_into_container"
SHRINK_INTO = "shrink_into_container"
ALIGN = "align_to_group"
EQUALIZE = "equalize_pitch"
SEPARATE = "separate_siblings"
SHRINK_FONT = "shrink_font"
WIDEN = "widen_box"
SHRINK_FONT_FLOOR = "shrink_font_to_floor"
GROW_HEIGHT = "grow_height"
SHRINK_FONT_HEIGHT = "shrink_font_to_fit_height"
RECOLOR = "recolor_text"
ENLARGE = "enlarge_control"
RAISE_FONT = "raise_font_size"


@dataclass
class Diagnosis:
    issue: Issue
    cause: str
    strategies: list[str]
    evidence: dict[str, float | str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"issue": self.issue.key, "cause": self.cause, "strategies": list(self.strategies),
                "evidence": self.evidence}


def _container_box(doc: DesignDocument, comp_id: str, code: str) -> BBox:
    comp = doc.require(comp_id)
    if code == I.OVERFLOW_PAGE or comp.parent_id is None:
        return BBox(x=0, y=0, w=doc.page.width, h=doc.page.height)
    return doc.require(comp.parent_id).bbox


def diagnose(doc: DesignDocument, issue: Issue, c: LayoutConstraints) -> Diagnosis:
    code = issue.code
    cid = issue.component_ids[0]
    if code in (I.OVERFLOW_PARENT, I.OVERFLOW_PAGE):
        comp = doc.require(cid)
        box = _container_box(doc, cid, code)
        if comp.bbox.w > box.w or comp.bbox.h > box.h:
            return Diagnosis(issue, "the component is larger than its container", [SHRINK_INTO],
                             {"component_w": comp.bbox.w, "container_w": box.w})
        return Diagnosis(issue, "the component is displaced beyond the edge of its container",
                         [TRANSLATE_INTO], {"overshoot_px": issue.measure})
    if code == I.MISALIGNED:
        return Diagnosis(issue, "a sibling sits slightly off the edge its neighbours share", [ALIGN],
                         dict(issue.details))
    if code == I.UNEVEN_SPACING:
        return Diagnosis(issue, "one or more repeated items are displaced from a uniform pitch",
                         [EQUALIZE], dict(issue.details))
    if code == I.OVERLAP:
        return Diagnosis(issue, "two siblings occupy the same area", [SEPARATE],
                         {"overlap_ratio": issue.measure})
    if code == I.TEXT_OVERFLOW:
        d = issue.details
        ratio = float(d["available"]) / max(float(d["estimated_width"]), 1e-6)
        order = [SHRINK_FONT, WIDEN, SHRINK_FONT_FLOOR] if ratio >= 0.75 else [WIDEN, SHRINK_FONT_FLOOR]
        return Diagnosis(issue, "the text is longer than the box can hold on one line", order,
                         {"fit_ratio": round(ratio, 3), **d})
    if code == I.TEXT_CLIPPED:
        return Diagnosis(issue, "the box is shorter than one line of its text",
                         [GROW_HEIGHT, SHRINK_FONT_HEIGHT], dict(issue.details))
    if code == I.LOW_CONTRAST:
        return Diagnosis(issue, "text and its background are too similar in luminance", [RECOLOR],
                         dict(issue.details))
    if code == I.TOUCH_TARGET_SMALL:
        return Diagnosis(issue, "the control is smaller than the minimum target size", [ENLARGE],
                         dict(issue.details))
    if code == I.FONT_TOO_SMALL:
        return Diagnosis(issue, "the font size is below the readable minimum", [RAISE_FONT],
                         dict(issue.details))
    return Diagnosis(issue, "unknown issue", [])
