"""Working-resolution normalization and illumination flattening."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class NormalizedImage:
    gray: np.ndarray  # uint8, illumination-flattened: paper ~255, ink dark
    color: np.ndarray  # uint8 BGR at working resolution (for diagnostics only)
    scale: float  # working pixels per original pixel
    original_size: tuple[int, int]  # (width, height)

    @property
    def width(self) -> int:
        return int(self.gray.shape[1])

    @property
    def height(self) -> int:
        return int(self.gray.shape[0])


def flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Divide out the paper background so shadows and gradients stop looking like ink.

    The background is estimated with a grayscale closing that erases thin dark strokes, then a
    heavy blur. The result is contrast-stretched so the darkest ink maps near 0.
    """
    k = max(15, int(round(min(gray.shape) * 0.02)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), max(8.0, k * 0.8))
    flat = cv2.divide(gray, np.maximum(background, 1), scale=255.0)
    lo = float(np.percentile(flat, 0.3))
    lo = min(lo, 200.0)  # a page with almost no ink must not be stretched into noise
    stretched = (flat.astype(np.float32) - lo) * (255.0 / max(255.0 - lo, 1.0))
    return np.clip(stretched, 0, 255).astype(np.uint8)


def normalize(bgr: np.ndarray, long_side: int = 1024, max_upscale: float = 2.0) -> NormalizedImage:
    h, w = bgr.shape[:2]
    scale = min(long_side / max(h, w), max_upscale)
    if abs(scale - 1.0) > 1e-3:
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        work = cv2.resize(bgr, (round(w * scale), round(h * scale)), interpolation=interp)
    else:
        work = bgr.copy()
        scale = 1.0
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    return NormalizedImage(
        gray=flatten_illumination(gray), color=work, scale=scale, original_size=(w, h)
    )
