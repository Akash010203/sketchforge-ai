"""Candidate binarizations. Each returns an ink mask (255 = ink) from a flattened gray image."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np


def otsu(flat: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(flat, (0, 0), 1.0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask


def adaptive(flat: np.ndarray) -> np.ndarray:
    block = max(15, int(round(max(flat.shape) / 28)) | 1)
    blurred = cv2.GaussianBlur(flat, (0, 0), 0.8)
    return cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 12
    )


def relative(flat: np.ndarray) -> np.ndarray:
    """Ink = pixels clearly darker than the (flattened) paper, with a noise-aware margin."""
    blurred = cv2.GaussianBlur(flat, (0, 0), 1.0)
    paper = float(np.median(blurred))
    # Robust noise estimate from the bright half of the image (almost entirely paper).
    bright = blurred[blurred >= paper]
    sigma = 1.4826 * float(np.median(np.abs(bright - np.median(bright)))) if bright.size else 4.0
    margin = max(30.0, 6.0 * sigma)
    return (blurred < paper - margin).astype(np.uint8) * 255


VARIANTS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "otsu": otsu,
    "adaptive": adaptive,
    "relative": relative,
}
