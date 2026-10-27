"""Losses for the component detector: Focal Loss (classification) + GIoU (bounding boxes)."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class FocalLoss(nn.Module):
    """Focal Loss for imbalanced multi-class classification.

    FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)
    """
    def __init__(self, gamma: float = 2.0, alpha: float | None = None, reduction: str = "mean"):
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce = F.cross_entropy(logits, targets, reduction="none")
        p_t = torch.exp(-ce)
        focal_weight = (1 - p_t) ** self.gamma
        if self.alpha is not None:
            focal_weight = focal_weight * self.alpha
        loss = focal_weight * ce
        if self.reduction == "mean":
            return loss.mean()
        if self.reduction == "sum":
            return loss.sum()
        return loss


def giou_loss(pred_boxes: torch.Tensor, target_boxes: torch.Tensor) -> torch.Tensor:
    """Generalised IoU loss between predicted and target boxes (cx, cy, w, h format).

    Args:
        pred_boxes:   (N, 4) tensor in [cx, cy, w, h] normalised [0, 1]
        target_boxes: (N, 4) tensor in the same format
    Returns:
        Scalar mean GIoU loss.
    """
    # Convert to (x1, y1, x2, y2)
    def _to_xyxy(b: torch.Tensor) -> torch.Tensor:
        return torch.stack([
            b[:, 0] - b[:, 2] / 2,
            b[:, 1] - b[:, 3] / 2,
            b[:, 0] + b[:, 2] / 2,
            b[:, 1] + b[:, 3] / 2,
        ], dim=-1)

    pb = _to_xyxy(pred_boxes)
    tb = _to_xyxy(target_boxes)

    # Intersection
    inter_x1 = torch.max(pb[:, 0], tb[:, 0])
    inter_y1 = torch.max(pb[:, 1], tb[:, 1])
    inter_x2 = torch.min(pb[:, 2], tb[:, 2])
    inter_y2 = torch.min(pb[:, 3], tb[:, 3])
    inter_w  = (inter_x2 - inter_x1).clamp(min=0)
    inter_h  = (inter_y2 - inter_y1).clamp(min=0)
    inter    = inter_w * inter_h

    # Union
    area_p = (pb[:, 2] - pb[:, 0]) * (pb[:, 3] - pb[:, 1])
    area_t = (tb[:, 2] - tb[:, 0]) * (tb[:, 3] - tb[:, 1])
    union  = (area_p + area_t - inter).clamp(min=1e-6)
    iou    = inter / union

    # Enclosing box
    enc_x1 = torch.min(pb[:, 0], tb[:, 0])
    enc_y1 = torch.min(pb[:, 1], tb[:, 1])
    enc_x2 = torch.max(pb[:, 2], tb[:, 2])
    enc_y2 = torch.max(pb[:, 3], tb[:, 3])
    enc_area = ((enc_x2 - enc_x1) * (enc_y2 - enc_y1)).clamp(min=1e-6)

    giou = iou - (enc_area - union) / enc_area
    return (1 - giou).mean()


class DetectorLoss(nn.Module):
    """Combined classification + bounding-box loss for the component detector."""

    def __init__(
        self,
        cls_weight: float = 1.0,
        box_weight: float = 2.0,
        gamma: float = 2.0,
        label_smoothing: float = 0.05,
    ):
        super().__init__()
        self.cls_criterion = FocalLoss(gamma=gamma)
        self.cls_weight    = cls_weight
        self.box_weight    = box_weight
        # Smooth L1 as an auxiliary box loss alongside GIoU
        self.smooth_l1    = nn.SmoothL1Loss()

    def forward(
        self,
        outputs: dict[str, torch.Tensor],
        targets: dict[str, torch.Tensor],
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            outputs: dict with "class_logits" (N, C) and optionally "box_preds" (N, 4)
            targets: dict with "class_ids" (N,) and optionally "boxes" (N, 4)
        """
        cls_logits = outputs["class_logits"]
        cls_ids    = targets["class_ids"]
        cls_loss   = self.cls_criterion(cls_logits, cls_ids)

        box_loss = torch.zeros(1, device=cls_logits.device, dtype=cls_logits.dtype).squeeze()
        if "box_preds" in outputs and "boxes" in targets:
            box_preds = outputs["box_preds"]
            gt_boxes  = targets["boxes"]
            box_loss  = giou_loss(box_preds, gt_boxes) + self.smooth_l1(box_preds, gt_boxes)

        total = self.cls_weight * cls_loss + self.box_weight * box_loss
        return {"loss": total, "cls_loss": cls_loss, "box_loss": box_loss}
