"""Dataset for component detector training.

Wraps the synthetic sketch generator plus (optionally) manifest-described real data.
Each sample is a pair:
    image  — (1, H, W) float32 grayscale ink mask in [0, 1]
    targets — list of dicts:  {class_idx, cx, cy, w, h}  all in [0, 1] (normalised)

This module requires PyTorch.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class DetectorSample:
    """A single training sample."""
    image: "np.ndarray"   # (H, W) float32, [0, 1]
    boxes: list[tuple[float, float, float, float]]   # (cx, cy, w, h) normalised
    labels: list[int]     # class index per box
    source: str = "synthetic"


_TYPE_ALIASES = {"page": "container", "nav": "sidebar", "navigation": "sidebar"}


def truth_to_targets(
    truth: dict[str, Any], image_w: int, image_h: int,
) -> tuple[list[tuple[float, float, float, float]], list[int]]:
    """Read generator annotations into normalized center/size boxes and class ids."""
    from sketchforge.models.component_detector.architecture import CLASS_TO_IDX

    boxes, labels = [], []
    components = truth.get("components", [])
    if not components and truth.get("bboxes"):
        components = [
            {"type": item.get("label", "unknown"),
             "bbox": [item.get("x", 0), item.get("y", 0),
                      item.get("w", 0), item.get("h", 0)]}
            for item in truth["bboxes"]
        ]
    for component in components:
        kind = _TYPE_ALIASES.get(str(component.get("type", "unknown")).lower(),
                                 str(component.get("type", "unknown")).lower())
        label = CLASS_TO_IDX.get(kind, CLASS_TO_IDX["unknown"])
        x, y, w, h = map(float, component["bbox"])
        if w <= 0 or h <= 0:
            continue
        boxes.append(((x + w / 2) / image_w, (y + h / 2) / image_h,
                      w / image_w, h / image_h))
        labels.append(label)
    return boxes, labels


class ProcessedDetectorDataset:
    """Read labeled samples emitted by ``scripts/process_datasets.py``.

    Samples without boxes are skipped. Box coordinates remain in source image
    pixels and are normalized after aspect-preserving resize.
    """

    def __init__(self, data_dir: str | Path, target_size: int = 512) -> None:
        import json

        self.data_dir = Path(data_dir)
        self.target_size = target_size
        manifest = json.loads((self.data_dir / "manifest.json").read_text(encoding="utf-8"))
        self.records = [r for r in manifest.get("samples", []) if r.get("has_detection_labels")]

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> DetectorSample:
        import cv2
        record = self.records[index]
        path = self.data_dir / record["image"]
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"cannot read detector image: {path}")
        h, w = bgr.shape[:2]
        scale = self.target_size / max(h, w)
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
        boxes, labels = truth_to_targets(record, w, h)
        return DetectorSample(image=_ink_mask(bgr), boxes=boxes, labels=labels,
                              source=str(record.get("source_dataset", "processed")))


def _ink_mask(bgr: np.ndarray) -> np.ndarray:
    """Convert a BGR sketch image to a normalised grayscale ink mask in [0, 1]."""
    import cv2
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    # Invert so ink = 1.0, paper = 0.0
    return 1.0 - gray


def _spec_to_boxes(
    spec: "Any",
    canvas_w: int,
    canvas_h: int,
) -> tuple[list[tuple[float, float, float, float]], list[int]]:
    """Convert a SketchSpec into normalised (cx, cy, w, h) + label lists."""
    from sketchforge.models.component_detector.architecture import CLASS_TO_IDX

    boxes, labels = [], []
    for el in spec.elements:
        if el.gt_type is None:
            continue  # not a labelled ground-truth element
        label = CLASS_TO_IDX.get(el.gt_type, CLASS_TO_IDX["unknown"])
        x, y, w, h = el.box
        cx = (x + w / 2) / canvas_w
        cy = (y + h / 2) / canvas_h
        nw = w / canvas_w
        nh = h / canvas_h
        if nw > 0.002 and nh > 0.002:  # skip degenerate boxes
            boxes.append((cx, cy, nw, nh))
            labels.append(label)
    return boxes, labels


class SyntheticDetectorDataset:
    """Infinite stream of synthetic detector samples.

    Args:
        layouts: mapping of layout-name -> callable returning a SketchSpec
        conditions: subset of ``CONDITIONS`` keys to draw from
        seeds: seed values to iterate through (deterministic)
        target_size: image is resized so its long side equals this
    """

    def __init__(
        self,
        layouts: "dict[str, Any]",
        conditions: list[str] | None = None,
        seeds: list[int] | None = None,
        target_size: int = 512,
    ) -> None:
        from sketchforge.datasets.synthetic_generator import CONDITIONS

        self.layouts = list(layouts.items())
        self.conditions = conditions or ["clean", "shadow", "noisy"]
        for c in self.conditions:
            if c not in CONDITIONS:
                raise ValueError(f"unknown condition {c!r}")
        self.seeds = seeds or list(range(100))
        self.target_size = target_size

    def __len__(self) -> int:
        return len(self.layouts) * len(self.conditions) * len(self.seeds)

    def _get(self, layout_fn: "Any", condition: str, seed: int) -> DetectorSample:
        import cv2
        from sketchforge.datasets.synthetic_generator import render_sketch

        spec = layout_fn()
        bgr, _ = render_sketch(spec, seed=seed, condition=condition)
        cw, ch = spec.canvas
        # Resize preserving aspect ratio
        h, w = bgr.shape[:2]
        scale = self.target_size / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        # Canvas coordinates scale too
        cw_s, ch_s = cw * scale, ch * scale
        boxes, labels = _spec_to_boxes(spec, cw_s, ch_s)
        return DetectorSample(image=_ink_mask(bgr), boxes=boxes, labels=labels, source="synthetic")

    def __getitem__(self, index: int) -> DetectorSample:
        n_cond = len(self.conditions)
        n_seed = len(self.seeds)
        li = index // (n_cond * n_seed)
        rem = index % (n_cond * n_seed)
        ci = rem // n_seed
        si = rem % n_seed
        name, layout_fn = self.layouts[li]
        return self._get(layout_fn, self.conditions[ci], self.seeds[si])

    def torch_dataset(self) -> "Any":
        """Return a ``torch.utils.data.Dataset`` wrapping this dataset."""
        import torch
        from torch.utils.data import Dataset

        parent = self

        class _TorchDS(Dataset):
            def __len__(self) -> int:
                return len(parent)

            def __getitem__(self, idx: int) -> dict:
                sample = parent[idx]
                img = torch.from_numpy(sample.image).unsqueeze(0)  # (1, H, W)
                return {"image": img, "boxes": sample.boxes, "labels": sample.labels}

        return _TorchDS()
