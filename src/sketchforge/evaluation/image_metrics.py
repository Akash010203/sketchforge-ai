"""Pixel metrics between two renders (BGR uint8 arrays of equal size).

They answer "how much of the picture changed?", which is how a *minimal* patch is recognised.
They do not say whether the design is correct: visual similarity is not semantic correctness.
"""

from __future__ import annotations

import cv2
import numpy as np


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _check(a: np.ndarray, b: np.ndarray) -> None:
    if a.shape != b.shape:
        raise ValueError(f"image shapes differ: {a.shape} vs {b.shape}")


def changed_pixel_ratio(a: np.ndarray, b: np.ndarray, threshold: int = 8) -> float:
    _check(a, b)
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=-1 if a.ndim == 3 else None)
    return float((diff > threshold).mean())


def changed_bbox(a: np.ndarray, b: np.ndarray, threshold: int = 8) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the smallest rectangle containing every changed pixel, or None."""
    _check(a, b)
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=-1 if a.ndim == 3 else None) > threshold
    ys, xs = np.where(diff)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def ssim(a: np.ndarray, b: np.ndarray, sigma: float = 1.5) -> float:
    """Mean structural similarity (Gaussian window, grayscale, data range 255)."""
    _check(a, b)
    x, y = _gray(a).astype(np.float64), _gray(b).astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    blur = lambda im: cv2.GaussianBlur(im, (0, 0), sigma)  # noqa: E731
    mx, my = blur(x), blur(y)
    sxx, syy, sxy = blur(x * x) - mx * mx, blur(y * y) - my * my, blur(x * y) - mx * my
    num = (2 * mx * my + c1) * (2 * sxy + c2)
    den = (mx * mx + my * my + c1) * (sxx + syy + c2)
    return float((num / den).mean())
