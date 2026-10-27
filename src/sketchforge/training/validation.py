"""Validation loop: runs one evaluation epoch and returns EpochMetrics."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sketchforge.training.metrics import EpochMetrics
from sketchforge.training.metrics import detection_metrics

if TYPE_CHECKING:
    import torch
    from torch.utils.data import DataLoader


def validate_epoch(
    model: "torch.nn.Module",
    loader: "DataLoader",
    criterion: "torch.nn.Module",
    device: "torch.device",
    epoch: int,
    phase: str = "val",
    num_classes: int = 15,
    amp: bool = False,
    channels_last: bool = True,
) -> EpochMetrics:
    """Run one pass over ``loader`` without gradients and return metrics."""
    import torch

    model.eval()
    total_loss = 0.0
    total_acc = 0.0
    total_cls_loss = 0.0
    total_box_loss = 0.0
    n_batches = 0
    all_predictions: list[list[dict]] = []
    all_targets: list[dict] = []
    t0 = time.perf_counter()

    with torch.no_grad():
        for images, targets in loader:
            images = images.to(device, non_blocking=True)
            if device.type == "cuda" and channels_last:
                images = images.contiguous(memory_format=torch.channels_last)
            from sketchforge.training.trainer import _loss_and_metrics
            loss, accuracy, cls_loss, box_loss, outputs = _loss_and_metrics(
                model, images, targets, num_classes, amp=amp, return_outputs=True)
            total_loss += loss.item()
            total_acc  += accuracy
            total_cls_loss += cls_loss.item()
            total_box_loss += box_loss.item()
            n_batches  += 1
            from sketchforge.training.detection_targets import decode_box_deltas, generate_anchors
            from sketchforge.models.component_detector.decoder import Detection, nms
            anchors = generate_anchors(outputs)
            for batch_i, target in enumerate(targets):
                logits = torch.cat([level[0][batch_i] for level in outputs], dim=0)
                deltas = torch.cat([level[1][batch_i] for level in outputs], dim=0)
                boxes = decode_box_deltas(anchors, deltas)
                probs = torch.softmax(logits, dim=-1)
                scores, labels = probs[:, 1:].max(dim=-1)
                top_count = min(100, scores.numel())
                top_scores, top_indices = scores.topk(top_count)
                keep = top_scores >= 0.05
                selected = top_indices[keep].cpu().tolist()
                scores_cpu = scores.cpu().tolist()
                labels_cpu = labels.cpu().tolist()
                boxes_cpu = boxes.cpu().tolist()
                pred_dets = [Detection(int(labels[idx]) + 1, "", float(scores_cpu[idx]),
                                       tuple(boxes_cpu[idx])) for idx in selected]
                pred_dets = nms(pred_dets, iou_threshold=0.5)
                all_predictions.append([{"label": d.class_id, "score": d.confidence, "box": d.bbox}
                                        for d in pred_dets])
                all_targets.append({"boxes": target["boxes"].cpu(), "labels": target["labels"].cpu()})

    n = max(n_batches, 1)
    mean_iou, map25, map35, map50 = detection_metrics(all_predictions, all_targets)
    mean_ap = (map25 + map35 + map50) / 3.0
    return EpochMetrics(
        epoch=epoch,
        phase=phase,
        loss=total_loss / n,
        cls_loss=total_cls_loss / n,
        box_loss=total_box_loss / n,
        accuracy=total_acc / n,
        mean_iou=mean_iou,
        mAP=mean_ap,
        mAP25=map25,
        mAP35=map35,
        mAP50=map50,
        samples=len(all_targets),
        duration_s=time.perf_counter() - t0,
    )
