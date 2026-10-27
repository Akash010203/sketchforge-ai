"""Semantic classification of geometric observations.

Geometric detection (contours, lines, text blobs) is separate from this step on purpose: a
rectangle does not prove a button. Every shape gets a *set* of candidate types with rule scores,
the winning type, the evidence that fired, and an ``ambiguous`` flag when the runner-up is close.

All absolute-size rules are expressed in *design pixels* (working pixels x design_scale), so the
same rule means the same thing for a 1024-wide desktop sketch and a 414-wide phone sketch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sketchforge.vision.confidence import best_and_ambiguity, combine_confidence, normalize_scores
from sketchforge.vision.contour_detection import Box, ShapeObservation
from sketchforge.vision.line_detection import LineObservation
from sketchforge.vision.region_proposals import RegionProposals
from sketchforge.vision.text_regions import TextRegion

CONTAINER_TYPES = {"header", "sidebar", "footer", "card", "container"}


@dataclass
class Detection:
    uid: int
    type: str
    bbox: Box  # working pixels
    confidence: float
    type_scores: dict[str, float]
    evidence: list[str]
    ambiguous: bool
    shape: ShapeObservation | None = None
    line: LineObservation | None = None
    text: TextRegion | None = None
    label_texts: list[TextRegion] = field(default_factory=list)  # text absorbed by a control
    corner_radius: float = 0.0  # working pixels
    recognized_text: str | None = None

    @property
    def area(self) -> float:
        return self.bbox[2] * self.bbox[3]


def area_fraction_inside(inner: Box, outer: Box) -> float:
    x1, y1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    x2 = min(inner[0] + inner[2], outer[0] + outer[2])
    y2 = min(inner[1] + inner[3], outer[1] + outer[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = inner[2] * inner[3]
    return inter / area if area > 0 else 0.0


def _center(box: Box) -> tuple[float, float]:
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def _center_in(inner: Box, outer: Box) -> bool:
    cx, cy = _center(inner)
    return outer[0] <= cx <= outer[0] + outer[2] and outer[1] <= cy <= outer[1] + outer[3]


def _score_shape(
    s: ShapeObservation,
    inner_shapes: list[ShapeObservation],
    direct_texts: list[TextRegion],
    proposals: RegionProposals,
    scale: float,
) -> tuple[dict[str, float], list[str]]:
    fx, fy, fw, fh = proposals.frame.bbox
    sw = proposals.stroke_width
    x, y, w, h = s.bbox
    wd, hd = w * scale, h * scale
    aspect = w / h
    tol_x, tol_y = 0.025 * fw + 1.5 * sw, 0.025 * fh + 1.5 * sw
    touch_top, touch_bottom = abs(y - fy) <= tol_y, abs((y + h) - (fy + fh)) <= tol_y
    touch_left, touch_right = abs(x - fx) <= tol_x, abs((x + w) - (fx + fw)) <= tol_x
    n_touch = sum((touch_top, touch_bottom, touch_left, touch_right))
    n_children, n_texts = len(inner_shapes), len(direct_texts)
    scores: dict[str, float] = {}
    why: dict[str, list[str]] = {}

    def fire(kind: str, value: float, reason: str) -> None:
        if value > scores.get(kind, 0.0):
            scores[kind] = value
        why.setdefault(kind, []).append(reason)

    # --- image placeholder -------------------------------------------------------------------
    if s.x_mark >= 0.75:
        fire("image", 0.95, "box with both diagonals drawn (image-placeholder convention)")
    elif (s.kind in ("rect", "rounded_rect") and n_children == 0 and n_texts == 0
          and w * h >= 0.02 * fw * fh and 0.35 <= aspect <= 3.5 and not (touch_top or touch_left)):
        fire("image", 0.40, "large empty box (could also be a container)")

    # --- page regions --------------------------------------------------------------------------
    if touch_top and touch_left and touch_right and h <= 0.22 * fh:
        fire("header", 0.92, "spans the page width at the top")
    elif touch_top and w >= 0.6 * fw and h <= 0.25 * fh:
        fire("header", 0.55, "wide box at the top of the page")
    if touch_bottom and touch_left and touch_right and h <= 0.22 * fh:
        fire("footer", 0.90, "spans the page width at the bottom")
    elif touch_bottom and w >= 0.6 * fw and h <= 0.25 * fh:
        fire("footer", 0.55, "wide box at the bottom of the page")
    if (touch_left != touch_right) and h >= 0.45 * fh and w <= 0.40 * fw:
        fire("sidebar", 0.88, "tall narrow box against a side of the page")

    # --- small controls ------------------------------------------------------------------------
    small = max(wd, hd) <= 46 and min(wd, hd) >= 10
    if s.kind == "circle" and small:
        fire("radio", 0.90, "small ring outline")
    elif s.kind in ("rect", "rounded_rect") and small and 0.7 <= aspect <= 1.4 and n_texts == 0 and n_children == 0:
        fire("checkbox", 0.85, "small empty square")

    # --- buttons and inputs: the classic ambiguity -------------------------------------------
    control_like = (
        s.kind in ("rect", "rounded_rect") and 24 <= hd <= 96 and aspect >= 1.5 and wd >= 50
        and n_children == 0 and n_texts <= 2
    )
    if control_like:
        b, i = 0.40, 0.40
        b_why, i_why = ["control-sized box"], ["control-sized box"]
        if n_texts >= 1:
            label = direct_texts[0]
            lx, ly, lw, lh = label.bbox
            centered = abs((lx + lw / 2) - (x + w / 2)) <= 0.12 * w
            left_aligned = (lx - x) <= 0.25 * w and (lx + lw / 2) < (x + w / 2)
            if centered:
                b += 0.30
                b_why.append("label is centred")
            elif left_aligned:
                i += 0.30
                i_why.append("label is left-aligned")
        else:
            i += 0.12
            i_why.append("empty box (fields are often left blank)")
        if s.kind == "rounded_rect":
            b += 0.20
            b_why.append("rounded corners")
        if s.fill_ratio >= 0.45:
            b += 0.10
            b_why.append("filled interior")
        if aspect >= 5:
            i += 0.10
            i_why.append("very wide box")
        fire("button", b, "; ".join(b_why))
        fire("input", i, "; ".join(i_why))

    # --- containers ----------------------------------------------------------------------------
    has_content = n_children >= 1 or n_texts >= 2 or (n_texts >= 1 and hd > 96)
    if has_content and w >= 0.10 * fw and h >= 0.08 * fh:
        floating = n_touch <= 1 and (w * h) <= 0.55 * fw * fh
        if floating:
            fire("card", 0.66, "floating box containing other elements")
            fire("container", 0.30, "generic grouping")
        else:
            fire("container", 0.60, "large box containing other elements")
            fire("card", 0.35, "box containing other elements")
    elif n_children >= 2:
        fire("container", 0.45, "box containing several elements")

    if not scores:
        fire("unknown", 0.20, "no rule matched")
    evidence = [f"{k}: {'; '.join(v)}" for k, v in why.items()]
    return scores, evidence


def detect_components(proposals: RegionProposals, design_scale: float) -> list[Detection]:
    shapes = proposals.shapes
    texts = proposals.texts
    detections: list[Detection] = []
    absorbed: set[int] = set()

    inner_of: dict[int, list[ShapeObservation]] = {}
    for s in shapes:
        inner_of[s.uid] = [
            o for o in shapes
            if o.uid != s.uid and o.area < s.area and area_fraction_inside(o.bbox, s.bbox) >= 0.85
        ]

    for s in shapes:
        inner = inner_of[s.uid]
        inner_boxes = [o.bbox for o in inner]
        direct_texts = [
            t for t in texts
            if _center_in(t.bbox, s.bbox) and not any(_center_in(t.bbox, b) for b in inner_boxes)
        ]
        scores, evidence = _score_shape(s, inner, direct_texts, proposals, design_scale)
        best, best_score, ambiguous = best_and_ambiguity(scores)
        label_texts: list[TextRegion] = []
        if best in ("button", "input"):
            label_texts = direct_texts
            absorbed.update(t.uid for t in label_texts)
        detections.append(
            Detection(
                uid=-1, type=best, bbox=s.bbox,
                confidence=combine_confidence(best_score, s.confidence),
                type_scores=normalize_scores(scores),
                evidence=[*s.evidence, *evidence],
                ambiguous=ambiguous, shape=s, label_texts=label_texts,
                corner_radius=s.corner_radius,
                recognized_text=" ".join(t.recognized_text for t in label_texts if t.recognized_text)
                or None,
            )
        )

    free_texts = [t for t in texts if t.uid not in absorbed]
    heights = np.array([t.bbox[3] for t in free_texts], dtype=float)
    median_h = float(np.median(heights)) if len(heights) >= 3 else 0.0
    for t in free_texts:
        hd = t.bbox[3] * design_scale
        ratio = (t.bbox[3] / median_h) if median_h > 0 else 1.0
        heading = float(np.clip((ratio - 1.25) / 0.5, 0.0, 1.0))
        if hd >= 30:
            heading = max(heading, 0.8)
        scores = {"heading": 0.15 + 0.80 * heading, "text": 0.15 + 0.80 * (1.0 - heading)}
        graphic = ""
        if hd >= 28 and t.bbox[2] / t.bbox[3] <= 1.4:
            # Handwritten words are wide. A large, squarish ink cluster is more likely a drawn
            # graphic (logo, icon) than a word; keep "heading" close behind so it is flagged.
            scores = {"image": 0.50, "heading": 0.40, "text": 0.15}
            graphic = "large squarish ink cluster (graphic or very short heading)"
        best, best_score, ambiguous = best_and_ambiguity(scores)
        detections.append(
            Detection(
                uid=-1, type=best, bbox=t.bbox,
                confidence=combine_confidence(best_score, t.confidence),
                type_scores=normalize_scores(scores),
                evidence=[graphic or (f"handwriting OCR: {t.recognized_text}" if t.recognized_text else
                                      f"handwriting-like stroke cluster ({t.pieces} pieces); text content unknown"),
                          f"height {hd:.0f} design px" + (f", {ratio:.2f}x the median text" if median_h else "")],
                ambiguous=ambiguous, text=t, recognized_text=t.recognized_text,
            )
        )

    for ln in proposals.dividers:
        detections.append(
            Detection(
                uid=-1, type="divider", bbox=ln.bbox, confidence=combine_confidence(0.9, ln.confidence),
                type_scores={"divider": 1.0}, evidence=["long, straight, isolated stroke"],
                ambiguous=False, line=ln,
            )
        )

    detections.sort(key=lambda d: (round(d.bbox[1] / 10), d.bbox[0]))
    for i, d in enumerate(detections):
        d.uid = i
    return detections
