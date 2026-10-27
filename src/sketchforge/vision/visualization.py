"""Diagnostic overlays: what the detector saw, drawn on the working image."""

from __future__ import annotations

import cv2
import numpy as np

from sketchforge.vision.component_detection import Detection
from sketchforge.vision.region_proposals import PageFrame

_COLORS = {
    "header": (200, 120, 0), "sidebar": (200, 120, 0), "footer": (200, 120, 0),
    "card": (0, 150, 0), "container": (0, 150, 0),
    "button": (30, 30, 220), "input": (200, 0, 160), "checkbox": (200, 0, 160),
    "radio": (200, 0, 160), "image": (0, 140, 230), "divider": (140, 140, 0),
    "text": (90, 90, 90), "heading": (40, 40, 40), "unknown": (0, 0, 0),
}


def draw_detections(
    color_image: np.ndarray, detections: list[Detection], frame: PageFrame | None = None
) -> np.ndarray:
    out = color_image.copy()
    if frame is not None:
        x, y, w, h = (int(round(v)) for v in frame.bbox)
        cv2.rectangle(out, (x, y), (x + w, y + h), (255, 0, 255), 2)
    for d in detections:
        x, y, w, h = (int(round(v)) for v in d.bbox)
        color = _COLORS.get(d.type, (0, 0, 0))
        cv2.rectangle(out, (x, y), (x + w, y + max(h, 2)), color, 2)
        label = f"{d.type} {d.confidence:.2f}" + ("?" if d.ambiguous else "")
        cv2.putText(out, label, (x + 2, max(10, y - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1,
                    cv2.LINE_AA)
    return out
