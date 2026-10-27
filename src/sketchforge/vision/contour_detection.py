"""Closed-shape detection (rectangles, rounded rectangles, circles, filled blocks).

Geometry only: this module says "there is a closed, roughly rectangular outline here", never
"this is a button". Semantic classification lives in component_detection.py.

Approach: ``findContours`` on the ink mask returns, for every pen stroke ring, an *outer* contour
(the outside edge of the stroke) and a *hole* contour (the enclosed paper). Hole contours give the
interior of a drawn box and are insensitive to pen overshoot at corners; outer contours are needed
for boxes that merge with neighbours (a page frame with a header drawn into it).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

Box = tuple[float, float, float, float]  # x, y, w, h in working pixels


@dataclass
class ShapeObservation:
    uid: int
    kind: str  # rect | rounded_rect | circle | filled_rect
    bbox: Box  # estimated stroke centre-line box
    rectangularity: float  # contour area / bounding-box area
    circularity: float  # 4*pi*area / perimeter^2
    corner_fill: float  # share of corner squares covered by the interior (1.0 = sharp corners)
    corner_radius: float  # estimated, working px (0 for sharp corners)
    confidence: float  # geometric confidence only; not a semantic claim
    source: str  # 'hole' or 'outer'
    contour: np.ndarray = field(repr=False)
    fill_ratio: float = 0.0  # ink coverage inside the box
    x_mark: float = 0.0  # 0..1: how much of both diagonals is inked (image placeholder cue)
    evidence: list[str] = field(default_factory=list)

    @property
    def area(self) -> float:
        return self.bbox[2] * self.bbox[3]


def contour_depths(hierarchy: np.ndarray) -> list[int]:
    """Nesting depth of every contour (0 = outer stroke edge, 1 = enclosed paper, 2 = ...)."""
    parents = hierarchy[:, 3]
    depths = [0] * len(parents)
    for i in range(len(parents)):
        d, p = 0, int(parents[i])
        while p != -1:
            d += 1
            p = int(parents[p])
        depths[i] = d
    return depths


def _corner_fill(contour: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    mask = np.zeros((h, w), dtype=np.uint8)
    shifted = contour.copy()
    shifted[:, 0, 0] -= x
    shifted[:, 0, 1] -= y
    cv2.drawContours(mask, [shifted], -1, 255, -1)
    c = max(3, round(0.25 * min(w, h)))
    corners = (mask[:c, :c], mask[:c, w - c :], mask[h - c :, :c], mask[h - c :, w - c :])
    return float(np.mean([np.count_nonzero(m) / m.size for m in corners]))


def diagonal_score(ink: np.ndarray, bbox: Box, stroke_width: float) -> float:
    """How completely both diagonals of ``bbox`` are inked *and* the four side triangles between
    them are empty (a hand-drawn 'X' marks an image; a solid block must not qualify)."""
    x, y, w, h = bbox
    if w < 12 or h < 12:
        return 0.0
    r = max(1, round(stroke_width * 0.7))
    ih, iw = ink.shape

    def inked(px: float, py: float) -> bool:
        ix, iy = round(px), round(py)
        window = ink[max(0, iy - r) : min(ih, iy + r + 1), max(0, ix - r) : min(iw, ix + r + 1)]
        return bool(window.size > 0 and window.any())

    inset = 0.14
    fractions = []
    for (x0, y0, x1, y1) in (
        (x + inset * w, y + inset * h, x + (1 - inset) * w, y + (1 - inset) * h),
        (x + (1 - inset) * w, y + inset * h, x + inset * w, y + (1 - inset) * h),
    ):
        n = 40
        hits = sum(inked(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t) for t in np.linspace(0, 1, n))
        fractions.append(hits / n)
    probes = (
        (x + 0.5 * w, y + 0.2 * h),
        (x + 0.5 * w, y + 0.8 * h),
        (x + 0.2 * w, y + 0.5 * h),
        (x + 0.8 * w, y + 0.5 * h),
    )
    r_probe = max(1, round(stroke_width * 0.5))

    def probe_inked(px: float, py: float) -> bool:
        ix, iy = round(px), round(py)
        win = ink[max(0, iy - r_probe) : min(ih, iy + r_probe + 1),
                  max(0, ix - r_probe) : min(iw, ix + r_probe + 1)]
        return bool(win.size > 0 and win.any())

    empty = sum(not probe_inked(px, py) for px, py in probes)
    if empty < 3:
        return 0.0
    return float(min(fractions))


def _interior_fill(ink: np.ndarray, bbox: Box, stroke_width: float) -> float:
    x, y, w, h = bbox
    pad = 1.5 * stroke_width
    x0, y0 = max(0, round(x + pad)), max(0, round(y + pad))
    x1, y1 = min(ink.shape[1], round(x + w - pad)), min(ink.shape[0], round(y + h - pad))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 1.0
    region = ink[y0:y1, x0:x1]
    return float(np.count_nonzero(region)) / region.size


def _same_box(a: Box, b: Box, tol: float) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(
        (a[0], a[1], a[0] + a[2], a[1] + a[3]), (b[0], b[1], b[0] + b[2], b[1] + b[3]), strict=True))


def _iou(a: Box, b: Box) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def detect_shapes(
    ink: np.ndarray,
    stroke_width: float,
    min_side: int = 10,
    rect_min: float = 0.80,
    rounded_corner_fill: float = 0.74,
) -> list[ShapeObservation]:
    contours, hier = cv2.findContours(ink, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None or len(contours) == 0:
        return []
    hier = hier[0]
    depth = contour_depths(hier)
    half = stroke_width / 2.0
    max_dim = max(ink.shape)

    hole_shapes: list[ShapeObservation] = []
    outer_shapes: list[ShapeObservation] = []
    uid = 0

    for i, cnt in enumerate(contours):
        x, y, w, h = cv2.boundingRect(cnt)
        if min(w, h) < min_side or max(w, h) > 1.2 * max_dim:
            continue
        area = float(cv2.contourArea(cnt))
        if area <= 0:
            continue
        rect = area / (w * h)
        perimeter = cv2.arcLength(cnt, True)
        circ = 4.0 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else 0.0
        aspect = w / h
        is_hole = depth[i] % 2 == 1

        if is_hole:
            center_box: Box = (x - half, y - half, w + stroke_width, h + stroke_width)
            fill = _corner_fill(cnt, x, y, w, h) if (rect >= 0.6 or circ >= 0.75) else 0.0
            square_ish = 0.75 <= aspect <= 1.33
            as_rect = rect >= rect_min and 1 / 80 <= aspect <= 80
            # Small hand-drawn squares (checkboxes) have rounded, jittery interiors that can drop
            # rectangularity below the threshold; corner fill still tells them from circles.
            as_small_square = (not as_rect) and rect >= 0.70 and fill >= 0.55 and square_ish
            if as_rect or as_small_square:
                rounded = fill < rounded_corner_fill
                radius = 0.0
                if rounded:
                    c = max(3, round(0.25 * min(w, h)))
                    radius = c * math.sqrt(max(0.0, (1.0 - fill) / 0.2146))
                conf = 0.45 + 0.40 * float(np.clip((rect - 0.70) / 0.28, 0, 1)) + 0.15
                note = "closed outline" if as_rect else "small square with distorted corners"
                hole_shapes.append(
                    ShapeObservation(
                        uid, "rounded_rect" if rounded else "rect", center_box, rect, circ, fill,
                        radius, conf, "hole", cnt,
                        evidence=[f"{note}, rectangularity {rect:.2f}"]
                        + ([f"rounded corners (fill {fill:.2f})"] if rounded else []),
                    )
                )
                uid += 1
            elif circ >= 0.75 and fill <= 0.52 and 0.7 <= aspect <= 1.43 and hier[i][3] != -1:
                parent = contours[int(hier[i][3])]
                parent_area = float(cv2.contourArea(parent))
                parent_per = cv2.arcLength(parent, True)
                parent_circ = (
                    4.0 * math.pi * parent_area / (parent_per * parent_per) if parent_per else 0.0
                )
                if parent_circ >= 0.70:  # the stroke around the hole is a ring too
                    conf = 0.45 + 0.40 * float(np.clip((circ - 0.75) / 0.2, 0, 1)) + 0.15
                    hole_shapes.append(
                        ShapeObservation(
                            uid, "circle", center_box, rect, circ, fill, 0.0, conf, "hole", cnt,
                            evidence=[f"ring outline, circularity {circ:.2f}, corner fill {fill:.2f}"],
                        )
                    )
                    uid += 1
        else:
            if rect < 0.80:
                continue
            center_box = (x + half, y + half, w - stroke_width, h - stroke_width)
            if center_box[2] < min_side or center_box[3] < min_side:
                continue
            child_areas = [
                float(cv2.contourArea(contours[j])) for j in range(len(contours)) if hier[j][3] == i
            ]
            ring_like = bool(child_areas) and max(child_areas) >= 0.08 * area
            fill = float(np.count_nonzero(ink[y : y + h, x : x + w])) / (w * h)
            if ring_like:
                conf = 0.40 + 0.40 * float(np.clip((rect - 0.80) / 0.18, 0, 1)) + 0.05
                outer_shapes.append(
                    ShapeObservation(
                        uid, "rect", center_box, rect, circ, 1.0, 0.0, conf, "outer", cnt,
                        evidence=[f"outer stroke boundary, rectangularity {rect:.2f}"],
                    )
                )
                uid += 1
            elif fill >= 0.6:
                outer_shapes.append(
                    ShapeObservation(
                        uid, "filled_rect", center_box, rect, circ, 1.0, 0.0, 0.5, "outer", cnt,
                        fill_ratio=fill, evidence=[f"solid block, fill {fill:.2f}"],
                    )
                )
                uid += 1

    # A ring yields an outer and a hole candidate for the same box: keep the hole (it ignores
    # pen overshoot). An outer candidate with no matching hole (a page frame whose interior is
    # split by a drawn header) survives.
    tol = max(2.0 * stroke_width, 8.0)
    survivors = list(hole_shapes)
    for outer in outer_shapes:
        if not any(_same_box(outer.bbox, h.bbox, tol) for h in hole_shapes):
            survivors.append(outer)

    # Near-duplicates (double-drawn boxes): keep the more confident one.
    survivors.sort(key=lambda s: -s.confidence)
    kept: list[ShapeObservation] = []
    for s in survivors:
        if all(not (s.source == k.source and _iou(s.bbox, k.bbox) >= 0.88) for k in kept):
            kept.append(s)

    for s in kept:
        if s.kind != "circle":
            s.fill_ratio = max(s.fill_ratio, _interior_fill(ink, s.bbox, stroke_width))
            s.x_mark = diagonal_score(ink, s.bbox, stroke_width)
            if s.x_mark >= 0.75:
                s.evidence.append(f"both diagonals inked ({s.x_mark:.2f}): image-placeholder cue")
    kept.sort(key=lambda s: (round(s.bbox[1] / 8), s.bbox[0]))
    for n, s in enumerate(kept):
        s.uid = n
    return kept
