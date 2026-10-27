"""Anchor generation and ground-truth assignment for the component detector."""
from __future__ import annotations


def generate_anchors(outputs):
    import torch
    from sketchforge.models.component_detector.architecture import ANCHOR_RATIOS, ANCHOR_SCALES

    device = outputs[0][0].device
    anchors_by_level = []
    for level, (logits, _) in enumerate(outputs):
        cells = logits.shape[1] // 9
        side = int(cells ** 0.5)
        if side * side != cells:
            raise ValueError(f"Expected square feature map; got {cells} cells")
        coords = (torch.arange(side, device=device, dtype=torch.float32) + .5) / side
        yy, xx = torch.meshgrid(coords, coords, indexing="ij")
        centers = torch.stack((xx, yy), -1).reshape(-1, 2).repeat_interleave(9, 0)
        sizes = torch.tensor([(scale * ratio ** .5, scale / ratio ** .5)
                              for _ in range(cells) for scale in ANCHOR_SCALES
                              for ratio in ANCHOR_RATIOS], device=device)
        anchors_by_level.append(torch.cat((centers, sizes), dim=1))
    return torch.cat(anchors_by_level)


def decode_box_deltas(anchors, deltas):
    """Decode normalized center/size anchor offsets into valid image boxes."""
    import torch

    centers = (anchors[:, :2] + deltas[..., :2] * anchors[:, 2:]).clamp(0.0, 1.0)
    sizes = (anchors[:, 2:] * deltas[..., 2:].clamp(-5, 5).exp()).clamp(1e-4, 1.0)
    return torch.cat((centers, sizes), dim=-1)


def match_batch(outputs, targets, num_classes: int):
    import torch

    device = outputs[0][0].device
    anchors = generate_anchors(outputs)
    logits = torch.cat([item[0] for item in outputs], dim=1)
    deltas = torch.cat([item[1] for item in outputs], dim=1)
    if logits.shape[-1] != num_classes:
        raise ValueError(f"Model emits {logits.shape[-1]} classes; expected {num_classes}")
    class_ids = torch.zeros(logits.shape[:2], dtype=torch.long, device=device)
    box_targets = torch.zeros_like(deltas)
    positive = torch.zeros(logits.shape[:2], dtype=torch.bool, device=device)
    a1, a2 = anchors[:, :2] - anchors[:, 2:] / 2, anchors[:, :2] + anchors[:, 2:] / 2
    for batch_i, target in enumerate(targets):
        boxes = target["boxes"].to(device)
        labels = target["labels"].to(device)
        if boxes.numel() == 0:
            continue
        b1, b2 = boxes[:, :2] - boxes[:, 2:] / 2, boxes[:, :2] + boxes[:, 2:] / 2
        extent = (torch.minimum(a2[:, None], b2[None]) -
                  torch.maximum(a1[:, None], b1[None])).clamp(min=0)
        intersection = extent[..., 0] * extent[..., 1]
        area_a = anchors[:, 2] * anchors[:, 3]
        area_b = boxes[:, 2] * boxes[:, 3]
        iou = intersection / (area_a[:, None] + area_b[None] - intersection).clamp(min=1e-8)
        best_iou, best_gt = iou.max(dim=1)
        forced = iou.argmax(dim=0)
        pos = best_iou >= 0.35
        pos[forced] = True
        gt = boxes[best_gt[pos]]
        anc = anchors[pos]
        class_ids[batch_i, pos] = labels[best_gt[pos]]
        positive[batch_i] = pos
        box_targets[batch_i, pos, :2] = (gt[:, :2] - anc[:, :2]) / anc[:, 2:].clamp(min=1e-6)
        box_targets[batch_i, pos, 2:] = torch.log(gt[:, 2:].clamp(min=1e-6) /
                                                   anc[:, 2:].clamp(min=1e-6))
    return logits, deltas, class_ids, box_targets, positive
