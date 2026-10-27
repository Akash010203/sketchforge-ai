"""Straight horizontal/vertical stroke detection (divider candidates)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class LineObservation:
    uid: int
    orientation: str  # 'h' or 'v'
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float
    straightness: float  # 0..1
    confidence: float

    @property
    def length(self) -> float:
        return float(np.hypot(self.x2 - self.x1, self.y2 - self.y1))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        x, y = min(self.x1, self.x2), min(self.y1, self.y2)
        t = max(self.thickness, 1.0)
        if self.orientation == "h":
            return (x, y - t / 2, abs(self.x2 - self.x1), t)
        return (x - t / 2, y, t, abs(self.y2 - self.y1))


def _detect_horizontal(ink: np.ndarray, stroke_width: float, min_length: int) -> list[tuple]:
    pad = max(1, round(stroke_width * 0.6))
    tolerant = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2 * pad + 1)))
    opened = cv2.morphologyEx(
        tolerant, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (min_length, 1))
    )
    n, _, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    found = []
    max_band = 3.0 * stroke_width + 2 * pad + 4
    for k in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[k])
        if w < min_length or h > max_band or area / (w * h) < 0.6:
            continue
        sub = ink[max(0, y - pad) : y + h + pad, x : x + w]
        ys, xs = np.nonzero(sub)
        if xs.size < w:
            continue
        ys = ys + max(0, y - pad)
        slope, intercept = np.polyfit(xs + x, ys, 1)
        resid = float(np.std(ys - (slope * (xs + x) + intercept)))
        if resid > 1.2 * stroke_width + 2.0 or abs(slope) > 0.08:
            continue
        thickness = float(xs.size) / w
        if thickness > 2.2 * stroke_width + 1.0:
            continue
        # A divider stands alone: the paper just above and below it is empty. A text baseline
        # has letters rising from it, so its neighbourhood is inked.
        cols = np.arange(x, x + w)
        yc = slope * cols + intercept
        offsets = np.arange(0.6 * stroke_width + 2.0, 3.6 * stroke_width + 2.0, 1.0)
        densities = []
        for sign in (-1, 1):
            rows = np.clip(np.round(yc[None, :] + sign * offsets[:, None]).astype(int), 0, ink.shape[0] - 1)
            densities.append(float(np.mean(ink[rows, cols[None, :]] > 0)))
        if max(densities) > 0.12:
            continue
        straight = float(np.clip(1.0 - resid / (1.2 * stroke_width + 2.0), 0.0, 1.0))
        found.append((x, slope * x + intercept, x + w, slope * (x + w) + intercept, thickness, straight))
    return found


def detect_lines(ink: np.ndarray, stroke_width: float, min_length: int = 30) -> list[LineObservation]:
    """Long, thin, straight strokes. Rectangle edges are included here and are removed later by
    region_proposals once the rectangles are known."""
    lines: list[LineObservation] = []
    for x1, y1, x2, y2, t, s in _detect_horizontal(ink, stroke_width, min_length):
        lines.append(LineObservation(0, "h", x1, y1, x2, y2, t, s, 0.5 + 0.5 * s))
    transposed = np.ascontiguousarray(ink.T)
    for y1, x1, y2, x2, t, s in _detect_horizontal(transposed, stroke_width, min_length):
        lines.append(LineObservation(0, "v", x1, y1, x2, y2, t, s, 0.5 + 0.5 * s))
    lines.sort(key=lambda ln: (ln.orientation, ln.y1 if ln.orientation == "h" else ln.x1))
    for i, ln in enumerate(lines):
        ln.uid = i
    return lines
