"""From detections to a valid, editable Design IR document.

Two separable steps:

``build_document``  maps a :class:`VisionResult` into the IR: page size and source transform,
                    component types/ids/hierarchy, theme styling, recognized or inferred text and
                    per-component detection provenance.
``refine_document`` makes the geometry self-consistent: children inside parents, near-aligned
                    siblings snapped, repeated groups evenly spaced. It reuses the same
                    alignment/spacing definitions the evaluator and repair engine use, so a freshly
                    built document does not start out with issues the evaluator would flag.

Text recognized by an enabled OCR model is preserved as user text; otherwise placeholder text is
flagged ``text_is_inferred``. Colours come from the theme.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.document import (
    ROOT_ID,
    add_component,
    make_component_id,
    new_document,
    preorder,
)
from sketchforge.design_ir.geometry import clamp_into, contains, intersection_area
from sketchforge.design_ir.schema import (
    CONTAINER_TYPES,
    BBox,
    CodeMapping,
    Component,
    ComponentType,
    DesignDocument,
    DetectionInfo,
    DocumentMetadata,
    Interaction,
    LayoutSpec,
    SourceTransform,
    Typography,
)
from sketchforge.design_ir.validation import validate_document
from sketchforge.domain.typography import line_box_height, placeholder_for
from sketchforge.layout.alignment import apply_alignment
from sketchforge.layout.grouping import alignable_siblings
from sketchforge.layout.overlap import sliver_trim
from sketchforge.layout.spacing import apply_spacing
from sketchforge.rendering.theme_engine import DEFAULT_THEME, Theme
from sketchforge.vision.component_detection import Detection
from sketchforge.vision.perspective import map_point_to_source
from sketchforge.vision.pipeline import VisionResult

MIN_FONT = 10.0
MAX_FONT = 64.0
LINE_HEIGHT = 1.3
_TYPE_FALLBACK = ComponentType.UNKNOWN
_DISPLAY_NAME = {
    "container": "Container", "header": "Header", "sidebar": "Sidebar", "footer": "Footer",
    "card": "Card", "button": "Button", "input": "Input", "text": "Text", "heading": "Heading",
    "image": "Image", "divider": "Divider", "checkbox": "Checkbox", "radio": "Radio",
    "unknown": "Element",
}


@dataclass
class BuildReport:
    notes: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    clamped: list[str] = field(default_factory=list)
    alignment_moves: int = 0
    spacing_moves: int = 0
    trimmed: int = 0

    def to_dict(self) -> dict:
        return {
            "notes": list(self.notes), "dropped": list(self.dropped), "clamped": list(self.clamped),
            "alignment_moves": self.alignment_moves, "spacing_moves": self.spacing_moves,
            "trimmed": self.trimmed,
        }


# ------------------------------------------------------------------------------------------
# build
# ------------------------------------------------------------------------------------------
def _component_type(name: str) -> ComponentType:
    try:
        return ComponentType(name)
    except ValueError:
        return _TYPE_FALLBACK


def _font_from_height(height_px: float) -> float:
    return round(min(MAX_FONT, max(MIN_FONT, height_px / LINE_HEIGHT)), 1)


def _text_fields(
    det: Detection, ctype: ComponentType, bbox: BBox, scale: float, theme: Theme
) -> tuple[str | None, bool, Typography | None, BBox]:
    """(text, text_is_inferred, typography, possibly-grown bbox) for a detection."""
    if ctype in (ComponentType.TEXT, ComponentType.HEADING):
        font = _font_from_height(bbox.h)
        typo = theme.typography_for(ctype, font)
        assert typo is not None
        text = det.recognized_text or placeholder_for(ctype.value, bbox.w, font, typo.font_weight)
        need = line_box_height(font, typo.line_height)
        if bbox.h < need:  # tiny handwriting: grow the box so the line is not clipped
            grow = need - bbox.h
            bbox = BBox(x=bbox.x, y=bbox.y - grow / 2, w=bbox.w, h=need)
        return text, det.recognized_text is None, typo, bbox
    if ctype in (ComponentType.BUTTON, ComponentType.INPUT):
        if det.label_texts:
            label_h = max(t.bbox[3] for t in det.label_texts) * scale
            font = min(24.0, max(12.0, _font_from_height(label_h)))
        else:
            font = round(min(18.0, max(12.0, 0.4 * bbox.h)), 1)
        typo = theme.typography_for(ctype, font)
        assert typo is not None
        pad = 12.0 if ctype is ComponentType.INPUT else 8.0
        text = det.recognized_text or placeholder_for(ctype.value, max(bbox.w - 2 * pad, 1.0), font, typo.font_weight)
        return text, det.recognized_text is None, typo, bbox
    return None, False, None, bbox


DIVIDER_THICKNESS = 2.0


def _slim_divider(box: BBox) -> BBox:
    """A drawn line is several px thick because pens are; a design divider is a hairline.
    Keep the centre line, drop the pen width."""
    if box.w >= box.h:
        return BBox(x=box.x, y=box.cy - DIVIDER_THICKNESS / 2, w=box.w, h=DIVIDER_THICKNESS)
    return BBox(x=box.cx - DIVIDER_THICKNESS / 2, y=box.y, w=DIVIDER_THICKNESS, h=box.h)


def _evidence(det: Detection) -> list[str]:
    out = []
    for item in det.evidence[:8]:
        out.append(item if len(item) <= 200 else item[:197] + "...")
    return out


def build_document(
    result: VisionResult,
    constraints: LayoutConstraints | None = None,
    *,
    name: str | None = None,
    theme: Theme = DEFAULT_THEME,
    refine: bool = True,
) -> tuple[DesignDocument, BuildReport]:
    """Convert a vision result into a validated Design IR document."""
    constraints = constraints or LayoutConstraints()
    report = BuildReport()
    scale = result.design_scale
    fx, fy, fw, fh = result.proposals.frame.bbox  # working px
    page_w, page_h = round(fw * scale, 3), round(fh * scale, 3)

    # design px per *source* px, offset in source px (design = (source - offset) * k)
    k = scale * result.normalized.scale
    # The frame origin is in corrected/working coordinates. Map it through the
    # inverse homography before recording the source-space offset, just as we
    # do for each detection's provenance bbox.
    frame_origin = (fx / result.normalized.scale, fy / result.normalized.scale)
    if result.perspective.corrected and result.perspective.matrix is not None:
        src_fx, src_fy = map_point_to_source(frame_origin, result.perspective.matrix)
    else:
        src_fx, src_fy = frame_origin
    meta = DocumentMetadata(
        source_image_sha256=result.loaded.sha256,
        source_size=(result.loaded.width, result.loaded.height),
        source_transform=SourceTransform(scale=k, offset_x=src_fx, offset_y=src_fy),
        notes=list(result.notes),
    )
    title = name or result.loaded.name or "Imported sketch"
    doc = new_document(
        title[:200], page_w, page_h,
        document_id=f"doc-{result.loaded.sha256[:8]}",
        device="mobile" if page_w <= 600 else "desktop",
        background=theme.page_background,
        metadata=meta,
    )
    page_box = BBox(x=0, y=0, w=page_w, h=page_h)

    uid_to_id: dict[int, str] = {}
    counters: dict[str, int] = {}
    for uid in result.inference.order:
        det = result.detections[uid]
        ctype = _component_type(det.type)
        x, y, w, h = det.bbox
        raw = BBox(x=(x - fx) * scale, y=(y - fy) * scale, w=max(w * scale, 1.0), h=max(h * scale, 1.0))
        bbox = clamp_into(raw, page_box) if raw.x2 > 0 and raw.y2 > 0 and raw.x < page_w and raw.y < page_h else None
        if bbox is None:
            report.dropped.append(f"detection #{uid} ({det.type}) lies outside the page frame")
            continue
        if ctype is ComponentType.DIVIDER:
            bbox = _slim_divider(bbox)
        text, inferred, typo, bbox = _text_fields(det, ctype, bbox, scale, theme)
        parent_uid = result.inference.parent.get(uid)
        parent_id = uid_to_id.get(parent_uid, ROOT_ID) if parent_uid is not None else ROOT_ID
        if parent_uid is not None and parent_uid not in uid_to_id:
            report.notes.append(f"{det.type} #{uid}: parent #{parent_uid} was dropped; attached to the page")
        comp_id = make_component_id(doc, ctype.value)
        counters[ctype.value] = counters.get(ctype.value, 0) + 1
        src = result.source_box(det.bbox)
        editable = ["bbox", "style"] if ctype in (ComponentType.IMAGE, ComponentType.DIVIDER) else None
        comp = Component(
            id=comp_id,
            type=ctype,
            name=f"{_DISPLAY_NAME.get(ctype.value, 'Element')} {counters[ctype.value]}",
            parent_id=parent_id,
            bbox=bbox,
            text=text,
            text_is_inferred=inferred,
            typography=typo,
            style=theme.style_for(ctype, det.corner_radius * scale if det.corner_radius else None),
            layout=LayoutSpec(mode="absolute", inferred=True) if ctype in CONTAINER_TYPES else None,
            detection=DetectionInfo(
                confidence=round(min(max(det.confidence, 0.0), 1.0), 4),
                source="heuristic",
                source_bbox=BBox(x=src[0], y=src[1], w=max(src[2], 1.0), h=max(src[3], 1.0)),
                type_scores={t: round(float(s), 4) for t, s in det.type_scores.items()},
                evidence=_evidence(det),
                ambiguous=det.ambiguous,
            ),
            codegen=CodeMapping(),
            **({"editable": editable} if editable else {}),
        )
        add_component(doc, comp)
        uid_to_id[uid] = comp_id

    _infer_interactions(doc)
    if refine:
        refine_document(doc, constraints, report)
        for container in preorder(doc):
            if container.type in CONTAINER_TYPES:
                container.layout = infer_container_layout(doc, container)
    validation = validate_document(doc)
    validation.raise_if_invalid()
    report.notes.extend(str(w) for w in validation.warnings)
    return doc, report


def _infer_interactions(doc: DesignDocument) -> None:
    for comp in doc.components:
        if comp.type is not ComponentType.BUTTON:
            continue
        siblings = doc.children_of(comp.parent_id) if comp.parent_id else []
        has_form = any(s.type is ComponentType.INPUT for s in siblings)
        comp.interactions = [
            Interaction(event="submit" if has_form else "click",
                        action="submit_form" if has_form else "none", inferred=True)
        ]


# ------------------------------------------------------------------------------------------
# refine
# ------------------------------------------------------------------------------------------
def enforce_containment(doc: DesignDocument, tolerance: float, report: BuildReport | None = None) -> int:
    """Pull children that poke out of their parent back inside (translate; shrink if larger)."""
    fixed = 0
    for comp in preorder(doc):  # parents first, so a moved parent is final before its children
        if comp.parent_id is None:
            continue
        parent = doc.require(comp.parent_id)
        if contains(parent.bbox, comp.bbox, tolerance):
            continue
        new_box = clamp_into(comp.bbox, parent.bbox)
        if new_box != comp.bbox:
            if report is not None:
                report.clamped.append(f"{comp.id} pulled inside {parent.id}")
            comp.bbox = new_box
            fixed += 1
    return fixed


def trim_slivers(doc: DesignDocument, constraints: LayoutConstraints, report: BuildReport | None = None) -> int:
    """Remove shallow overlaps between siblings by trimming one box (see layout/overlap.py)."""
    trimmed = 0
    for parent in preorder(doc):
        if parent.type not in CONTAINER_TYPES:
            continue
        kids = alignable_siblings(doc, parent.id)
        for i, a in enumerate(kids):
            for b in kids[i + 1 :]:
                inter = intersection_area(a.bbox, b.bbox)
                if inter <= 0 or inter / min(a.bbox.area, b.bbox.area) <= constraints.overlap_tolerance_ratio:
                    continue
                result = sliver_trim(a, b)
                if result is None:
                    continue
                victim, new = result
                victim.bbox = new
                if victim.text_is_inferred and victim.typography is not None:
                    victim.text = placeholder_for(victim.type.value, new.w, victim.typography.font_size,
                                                  victim.typography.font_weight)
                trimmed += 1
                if report is not None:
                    report.notes.append(f"trimmed {victim.id} to clear a shallow overlap with "
                                        f"{(b if victim is a else a).id}")
    return trimmed


def refine_document(
    doc: DesignDocument, constraints: LayoutConstraints, report: BuildReport | None = None
) -> BuildReport:
    report = report or BuildReport()
    enforce_containment(doc, constraints.containment_tolerance_px, report)
    report.trimmed = trim_slivers(doc, constraints, report)
    report.alignment_moves += apply_alignment(
        doc, constraints.align_snap_radius_px, constraints.align_tolerance_px
    )
    report.spacing_moves += apply_spacing(doc, constraints.spacing_tolerance_px)
    enforce_containment(doc, constraints.containment_tolerance_px, report)
    return report


def infer_container_layout(doc: DesignDocument, container: Component) -> LayoutSpec:
    """Describe how a container's children are arranged. Geometry stays authoritative; this is a
    constraint and code-generation hint, always marked ``inferred``."""
    kids = [c for c in doc.children_of(container.id) if c.type is not ComponentType.DIVIDER]
    box = container.bbox
    margins = [
        m for c in kids
        for m in (c.bbox.x - box.x, c.bbox.y - box.y, box.x2 - c.bbox.x2, box.y2 - c.bbox.y2)
    ]
    padding = round(max(0.0, min(margins)), 1) if margins else 0.0
    if len(kids) < 2:
        return LayoutSpec(mode="absolute", padding=padding, inferred=True)

    by_y = sorted(kids, key=lambda c: c.bbox.y)
    stacked = all(
        by_y[i + 1].bbox.y >= by_y[i].bbox.y2 - 0.2 * min(by_y[i].bbox.h, by_y[i + 1].bbox.h)
        for i in range(len(by_y) - 1)
    )
    by_x = sorted(kids, key=lambda c: c.bbox.x)
    sided = all(
        by_x[i + 1].bbox.x >= by_x[i].bbox.x2 - 0.2 * min(by_x[i].bbox.w, by_x[i + 1].bbox.w)
        for i in range(len(by_x) - 1)
    )
    if stacked:
        gaps = [by_y[i + 1].bbox.y - by_y[i].bbox.y2 for i in range(len(by_y) - 1)]
        lefts = [c.bbox.x for c in kids]
        centers = [c.bbox.cx for c in kids]
        rights = [c.bbox.x2 for c in kids]
        spread = {"start": max(lefts) - min(lefts), "center": max(centers) - min(centers),
                  "end": max(rights) - min(rights)}
        align = min(spread, key=spread.get)
        return LayoutSpec(mode="flex", direction="column", gap=round(max(0.0, statistics.median(gaps)), 1),
                          padding=padding, align_items=align if spread[align] <= 6.0 else "start",
                          inferred=True)
    if sided:
        gaps = [by_x[i + 1].bbox.x - by_x[i].bbox.x2 for i in range(len(by_x) - 1)]
        tops = [c.bbox.y for c in kids]
        centers = [c.bbox.cy for c in kids]
        bottoms = [c.bbox.y2 for c in kids]
        spread = {"start": max(tops) - min(tops), "center": max(centers) - min(centers),
                  "end": max(bottoms) - min(bottoms)}
        align = min(spread, key=spread.get)
        return LayoutSpec(mode="flex", direction="row", gap=round(max(0.0, statistics.median(gaps)), 1),
                          padding=padding, align_items=align if spread[align] <= 6.0 else "start",
                          inferred=True)
    return LayoutSpec(mode="absolute", padding=padding, inferred=True)
