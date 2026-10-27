"""Find candidate handwriting lines before optional OCR.

A text region is a cluster of small pen strokes left over after rectangle outlines, dividers and
image crosses are removed. Recognition is performed separately by :mod:`handwriting_ocr`.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from sketchforge.vision.contour_detection import ShapeObservation
from sketchforge.vision.line_detection import LineObservation


@dataclass
class TextRegion:
    uid: int
    bbox: tuple[float, float, float, float]
    ink_pixels: int
    pieces: int  # connected strokes (letters/words) inside the region
    confidence: float
    recognized_text: str | None = None

    @property
    def center(self) -> tuple[float, float]:
        return (self.bbox[0] + self.bbox[2] / 2, self.bbox[1] + self.bbox[3] / 2)


def residual_ink(
    ink: np.ndarray,
    shapes: list[ShapeObservation],
    lines: list[LineObservation],
    stroke_width: float,
) -> np.ndarray:
    """Ink with outlines of known shapes, dividers and image crosses erased."""
    resid = ink.copy()
    band = int(2 * stroke_width + 3)
    for s in shapes:
        cv2.drawContours(resid, [s.contour], -1, 0, thickness=band)
        if s.x_mark >= 0.75:
            x, y, w, h = s.bbox
            cv2.rectangle(resid, (round(x), round(y)), (round(x + w), round(y + h)), 0, -1)
    for ln in lines:
        cv2.line(resid, (round(ln.x1), round(ln.y1)), (round(ln.x2), round(ln.y2)), 0, band)
    return resid


def find_text_regions(
    ink: np.ndarray,
    shapes: list[ShapeObservation],
    lines: list[LineObservation],
    stroke_width: float,
    min_height: int = 5,
) -> list[TextRegion]:
    resid = residual_ink(ink, shapes, lines, stroke_width)
    h_img, w_img = resid.shape

    n0, labels0, stats0, _ = cv2.connectedComponentsWithStats(resid, connectivity=8)
    min_area = max(14, int(2.0 * stroke_width))
    keep = np.zeros(n0, dtype=bool)
    keep[1:] = stats0[1:, cv2.CC_STAT_AREA] >= min_area
    resid = (keep[labels0] * 255).astype(np.uint8)

    merge_w = max(9, round(0.0135 * w_img))
    merged = cv2.dilate(resid, cv2.getStructuringElement(cv2.MORPH_RECT, (merge_w, 3)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)

    regions: list[TextRegion] = []
    for k in range(1, n):
        member = (labels == k) & (resid > 0)
        ys, xs = np.nonzero(member)
        if xs.size == 0:
            continue
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        w, h = x1 - x0, y1 - y0
        if h < min_height or w < 10 or h > 0.12 * h_img or w > 0.9 * w_img:
            continue
        if w / h < 0.6:  # tall slivers are leftovers of erased outlines, not words
            continue
        pieces = int(cv2.connectedComponents(member.astype(np.uint8))[0]) - 1
        conf = float(np.clip(0.35 + 0.1 * min(pieces, 5) + 0.15 * min(w / h, 4) / 4, 0.0, 0.9))
        regions.append(TextRegion(0, (float(x0), float(y0), float(w), float(h)), int(xs.size), pieces, conf))

    regions = _merge_words_into_lines(regions)
    regions.sort(key=lambda r: (round(r.bbox[1] / 10), r.bbox[0]))
    for i, r in enumerate(regions):
        r.uid = i
    return regions


def _merge_words_into_lines(regions: list[TextRegion]) -> list[TextRegion]:
    """Join word blobs that sit on one line and are closer than about 1.2 line heights."""
    items = sorted(regions, key=lambda r: r.bbox[0])
    merged: list[TextRegion] = []
    for region in items:
        target = None
        for cand in merged:
            cx, cy, cw, ch = cand.bbox
            rx, ry, rw, rh = region.bbox
            gap = rx - (cx + cw)
            tall = max(ch, rh)
            same_line = abs((cy + ch / 2) - (ry + rh / 2)) <= 0.5 * tall
            if same_line and -2 <= gap <= 1.2 * tall:
                target = cand
                break
        if target is None:
            merged.append(region)
            continue
        x0 = min(target.bbox[0], region.bbox[0])
        y0 = min(target.bbox[1], region.bbox[1])
        x1 = max(target.bbox[0] + target.bbox[2], region.bbox[0] + region.bbox[2])
        y1 = max(target.bbox[1] + target.bbox[3], region.bbox[1] + region.bbox[3])
        target.bbox = (x0, y0, x1 - x0, y1 - y0)
        target.ink_pixels += region.ink_pixels
        target.pieces += region.pieces
        target.confidence = max(target.confidence, region.confidence)
    return merged
