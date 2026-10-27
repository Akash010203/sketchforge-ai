"""Mask cleanup helpers."""

from __future__ import annotations

import cv2
import numpy as np


def remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    """Drop connected components smaller than ``min_area`` pixels."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return (keep[labels] * 255).astype(np.uint8)


def speckle_fraction(mask: np.ndarray, small_area: int = 6) -> float:
    """Share of connected components that are tiny: a proxy for threshold noise."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return 0.0
    areas = stats[1:, cv2.CC_STAT_AREA]
    return float(np.mean(areas < small_area))


def estimate_stroke_width(mask: np.ndarray) -> float:
    """Typical pen width in pixels.

    The median distance-transform value on stroke ridges is about (width + 1) / 2 for a
    pixel-quantized stroke, so width ~= 2 * median - 1.
    """
    if not mask.any():
        return 2.0
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = (dist == cv2.dilate(dist, np.ones((3, 3), np.uint8))) & (dist > 0)
    values = dist[ridge]
    if values.size == 0:
        return 2.0
    return float(max(1.0, 2.0 * np.median(values) - 1.0))


def close_gaps(mask: np.ndarray, size: int) -> np.ndarray:
    """Morphological closing to bridge the small gaps left at hand-drawn corners."""
    size = max(3, int(size) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
