"""Component detection accuracy against ground truth.

Definitions (also in docs/EVALUATION.md):

* A prediction *matches* a ground-truth component when their IoU >= ``iou_threshold`` (thin
  boxes such as dividers are padded by ``thin_pad`` pixels in their thin dimension first, since a
  1-px position error would otherwise zero the IoU). Matching is greedy by descending IoU, one
  prediction per ground-truth component.
* Localization precision/recall/F1 ignore the predicted type.
* Type accuracy is the fraction of *matched* pairs whose types agree. It is conditional on
  localization and must be read together with recall.

Limitations: IoU 0.5 is lenient; text boxes depend on how the annotator drew them; accuracy on
synthetic sketches says little about real photographs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]


@dataclass
class BoxItem:
    type: str
    bbox: Box


@dataclass
class MatchResult:
    pairs: list[tuple[int, int, float]]  # (pred index, gt index, iou)
    unmatched_pred: list[int]
    unmatched_gt: list[int]


@dataclass
class DetectionScores:
    n_pred: int
    n_gt: int
    n_matched: int
    precision: float
    recall: float
    f1: float
    type_accuracy: float
    mean_iou: float
    mean_center_error_px: float
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    missed_types: dict[str, int] = field(default_factory=dict)
    extra_types: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def box_iou(a: Box, b: Box, thin_pad: float = 6.0, thin_limit: float = 8.0) -> float:
    def padded(box: Box) -> Box:
        x, y, w, h = box
        if h <= thin_limit:
            y, h = y - thin_pad, h + 2 * thin_pad
        if w <= thin_limit:
            x, w = x - thin_pad, w + 2 * thin_pad
        return x, y, w, h

    a, b = padded(a), padded(b)
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def match_boxes(pred: list[BoxItem], gt: list[BoxItem], iou_threshold: float = 0.5) -> MatchResult:
    candidates = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gt):
            score = box_iou(p.bbox, g.bbox)
            if score >= iou_threshold:
                candidates.append((score, i, j))
    candidates.sort(reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    pairs = []
    for score, i, j in candidates:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        pairs.append((i, j, score))
    return MatchResult(
        pairs,
        [i for i in range(len(pred)) if i not in used_p],
        [j for j in range(len(gt)) if j not in used_g],
    )


def score_detection(
    pred: list[BoxItem], gt: list[BoxItem], iou_threshold: float = 0.5
) -> DetectionScores:
    m = match_boxes(pred, gt, iou_threshold)
    n_matched = len(m.pairs)
    precision = n_matched / len(pred) if pred else 0.0
    recall = n_matched / len(gt) if gt else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    correct = sum(pred[i].type == gt[j].type for i, j, _ in m.pairs)
    confusion: dict[str, Counter] = {}
    center_errors = []
    for i, j, _ in m.pairs:
        confusion.setdefault(gt[j].type, Counter())[pred[i].type] += 1
        pc = (pred[i].bbox[0] + pred[i].bbox[2] / 2, pred[i].bbox[1] + pred[i].bbox[3] / 2)
        gc = (gt[j].bbox[0] + gt[j].bbox[2] / 2, gt[j].bbox[1] + gt[j].bbox[3] / 2)
        center_errors.append(((pc[0] - gc[0]) ** 2 + (pc[1] - gc[1]) ** 2) ** 0.5)
    return DetectionScores(
        n_pred=len(pred),
        n_gt=len(gt),
        n_matched=n_matched,
        precision=precision,
        recall=recall,
        f1=f1,
        type_accuracy=correct / n_matched if n_matched else 0.0,
        mean_iou=sum(s for _, _, s in m.pairs) / n_matched if n_matched else 0.0,
        mean_center_error_px=sum(center_errors) / len(center_errors) if center_errors else 0.0,
        confusion={k: dict(v) for k, v in confusion.items()},
        missed_types=dict(Counter(gt[j].type for j in m.unmatched_gt)),
        extra_types=dict(Counter(pred[i].type for i in m.unmatched_pred)),
    )
