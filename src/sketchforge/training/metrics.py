"""Training metrics: mAP, per-class AP, and confusion matrix for component detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class EpochMetrics:
    epoch: int
    phase: str          # "train" | "val" | "test"
    loss: float = 0.0
    cls_loss: float = 0.0
    box_loss: float = 0.0
    accuracy: float = 0.0   # top-1 anchor classification accuracy (background-heavy)
    mean_iou: float = 0.0   # mean IoU of matches at IoU >= 0.25
    mAP: float = 0.0        # mean AP over IoU thresholds 0.25, 0.35, and 0.50
    mAP25: float = 0.0
    mAP35: float = 0.0
    mAP50: float = 0.0
    samples: int = 0
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "epoch": self.epoch,
            "phase": self.phase,
            "loss": round(self.loss, 6),
            "cls_loss": round(self.cls_loss, 6),
            "box_loss": round(self.box_loss, 6),
            "accuracy": round(self.accuracy, 4),
            "mean_iou": round(self.mean_iou, 4),
            "mAP": round(self.mAP, 4),
            "mAP@0.25": round(self.mAP25, 4),
            "mAP@0.35": round(self.mAP35, 4),
            "mAP@0.50": round(self.mAP50, 4),
            "samples": self.samples,
            "duration_s": round(self.duration_s, 2),
        }

    def summary(self) -> str:
        return (
            f"[{self.phase}] epoch={self.epoch} loss={self.loss:.4f} "
            f"anchor_acc={self.accuracy:.3f} IoU25={self.mean_iou:.3f} "
            f"mAP25/35/50={self.mAP25:.3f}/{self.mAP35:.3f}/{self.mAP50:.3f}"
        )


def compute_iou(pred_boxes: "list[tuple]", true_boxes: "list[tuple]") -> float:
    """Compute mean IoU between predicted and ground-truth boxes.

    Each box is (x, y, w, h) in pixel coordinates.
    Simplified: matches predictions to GT by index order (for smoke tests).
    """
    if not pred_boxes or not true_boxes:
        return 0.0
    ious: list[float] = []
    for pb, tb in zip(pred_boxes, true_boxes):
        px, py, pw, ph = pb
        tx, ty, tw, th = tb
        inter_x = max(0, min(px + pw, tx + tw) - max(px, tx))
        inter_y = max(0, min(py + ph, ty + th) - max(py, ty))
        inter   = inter_x * inter_y
        union   = pw * ph + tw * th - inter
        ious.append(inter / union if union > 0 else 0.0)
    return sum(ious) / len(ious) if ious else 0.0


def compute_accuracy(logits: "torch.Tensor", labels: "torch.Tensor") -> float:
    """Top-1 accuracy from class logits."""
    import torch
    preds = logits.argmax(dim=-1)
    return (preds == labels).float().mean().item()


def detection_metrics(predictions: list[list[dict]], targets: list[dict],
                      iou_threshold: float | None = None) -> tuple[float, float, float, float]:
    """Return mean matched IoU and class-macro AP at IoU 0.25, 0.35, and 0.50.

    Predictions use normalized ``(cx, cy, w, h)`` boxes and contain ``label``
    and ``score``. AP uses the all-points precision envelope. Background (0)
    is excluded. Images without a class's ground truth still contribute false
    positives for that class.
    """
    def iou(a, b):
        ax1, ay1, ax2, ay2 = a[0]-a[2]/2, a[1]-a[3]/2, a[0]+a[2]/2, a[1]+a[3]/2
        bx1, by1, bx2, by2 = b[0]-b[2]/2, b[1]-b[3]/2, b[0]+b[2]/2, b[1]+b[3]/2
        inter = max(0., min(ax2, bx2)-max(ax1, bx1)) * max(0., min(ay2, by2)-max(ay1, by1))
        union = max(0., a[2])*max(0., a[3]) + max(0., b[2])*max(0., b[3]) - inter
        return inter / union if union > 0 else 0.

    labels = {int(label) for target in targets for label in target["labels"].tolist() if int(label) > 0}
    if not labels:
        return 0.0, 0.0, 0.0, 0.0
    all_ious = []
    threshold_aps = {threshold: [] for threshold in (0.25, 0.35, 0.50)}
    for label in sorted(labels):
        gt_by_image = {}
        total_gt = 0
        for image_i, target in enumerate(targets):
            boxes = target["boxes"].tolist()
            ids = target["labels"].tolist()
            gt = [box for box, cid in zip(boxes, ids) if int(cid) == label]
            gt_by_image[image_i] = gt
            total_gt += len(gt)
        ranked = sorted(
            [(float(pred["score"]), image_i, pred["box"])
             for image_i, image_preds in enumerate(predictions)
             for pred in image_preds if int(pred["label"]) == label], reverse=True,
        )
        if total_gt == 0:
            continue
        import numpy as np

        for threshold in threshold_aps:
            matched = {image_i: set() for image_i in range(len(targets))}
            tp, fp = [], []
            for _, image_i, box in ranked:
                candidates = [(iou(box, gt), j) for j, gt in enumerate(gt_by_image[image_i])
                              if j not in matched[image_i]]
                best_iou, best_j = max(candidates, default=(0., -1))
                if best_iou >= threshold:
                    matched[image_i].add(best_j)
                    tp.append(1.); fp.append(0.)
                    if threshold == 0.25:
                        all_ious.append(best_iou)
                else:
                    tp.append(0.); fp.append(1.)
            cum_tp = np.cumsum(tp, dtype=float)
            cum_fp = np.cumsum(fp, dtype=float)
            recall = cum_tp / total_gt
            precision = cum_tp / np.maximum(cum_tp + cum_fp, 1e-12)
            recall = np.concatenate(([0.], recall, [1.]))
            precision = np.concatenate(([0.], precision, [0.]))
            for i in range(len(precision) - 2, -1, -1):
                precision[i] = max(precision[i], precision[i + 1])
            changes = np.where(recall[1:] != recall[:-1])[0]
            threshold_aps[threshold].append(float(np.sum(
                (recall[changes + 1] - recall[changes]) * precision[changes + 1])))
    return (sum(all_ious) / len(all_ious) if all_ious else 0.0,
            *(sum(aps) / len(aps) if aps else 0.0 for aps in threshold_aps.values()))
