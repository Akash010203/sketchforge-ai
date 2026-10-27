"""Decoder: converts raw model outputs (logits + raw boxes) to structured predictions."""
from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # cx, cy, w, h in [0,1]
    bbox_px: tuple[float, float, float, float] | None = None  # x, y, w, h in pixels


from sketchforge.models.component_detector.architecture import COMPONENT_CLASSES

CLASS_NAMES = COMPONENT_CLASSES


def decode(
    class_logits: torch.Tensor,
    box_preds: torch.Tensor | None = None,
    conf_threshold: float = 0.3,
    image_wh: tuple[int, int] | None = None,
    max_detections: int = 300,
) -> list[Detection]:
    """Convert model outputs to a list of Detections.

    Args:
        class_logits: (N, C) raw class scores
        box_preds:    (N, 4) predicted boxes in [cx, cy, w, h] normalised, or None
        conf_threshold: minimum softmax confidence to include a detection
        image_wh:     (width, height) in pixels for converting to pixel coords
    """
    probs = torch.softmax(class_logits, dim=-1)  # (N, C)
    confs, class_ids = probs.max(dim=-1)         # (N,), (N,)

    eligible = torch.nonzero((class_ids > 0) & (confs >= conf_threshold), as_tuple=False).flatten()
    if eligible.numel() > max_detections:
        eligible = eligible[torch.topk(confs[eligible], max_detections).indices]
    rows = eligible.tolist()
    ids = class_ids[eligible].tolist()
    scores = confs[eligible].tolist()
    boxes = box_preds[eligible].tolist() if box_preds is not None else [None] * len(rows)

    detections: list[Detection] = []
    for cid, conf, box in zip(ids, scores, boxes, strict=True):
        name = CLASS_NAMES[cid] if cid < len(CLASS_NAMES) else f"cls_{cid}"

        bbox = (0.0, 0.0, 0.0, 0.0)
        bbox_px = None
        if box is not None:
            cx, cy, w, h = box
            bbox = (cx, cy, w, h)
            if image_wh is not None:
                W, H = image_wh
                bbox_px = (
                    (cx - w / 2) * W,
                    (cy - h / 2) * H,
                    w * W,
                    h * H,
                )

        detections.append(Detection(
            class_id=int(cid),
            class_name=name,
            confidence=float(conf),
            bbox=bbox,
            bbox_px=bbox_px,
        ))

    return detections


def nms(detections: list[Detection], iou_threshold: float = 0.5) -> list[Detection]:
    """Non-maximum suppression over a list of Detections (sorted by confidence desc)."""
    if not detections:
        return []
    sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
    kept: list[Detection] = []
    for det in sorted_dets:
        suppress = False
        for k in kept:
            if det.class_id == k.class_id and _box_iou(det.bbox, k.bbox) > iou_threshold:
                suppress = True
                break
        if not suppress:
            kept.append(det)
    return kept


def _box_iou(a: tuple, b: tuple) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax1, ay1, ax2, ay2 = ax - aw / 2, ay - ah / 2, ax + aw / 2, ay + ah / 2
    bx1, by1, bx2, by2 = bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0
