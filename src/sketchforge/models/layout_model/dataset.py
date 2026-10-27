"""Dataset for pixel-level UI layout maps derived from PNG/JSON pairs."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class LayoutDataset:
    def __init__(self, data_dir: str | Path, image_size: int = 256):
        self.root = Path(data_dir)
        self.image_size = image_size
        self.images = [p for p in sorted(self.root.glob("*.png"))
                       if p.with_suffix(".json").is_file()]

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        import cv2
        import torch
        from sketchforge.models.component_detector.architecture import CLASS_TO_IDX

        path = self.images[index]
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"Could not read {path}")
        h, w = bgr.shape[:2]
        image = cv2.resize(bgr, (self.image_size, self.image_size), interpolation=cv2.INTER_AREA)
        image = 1.0 - cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        truth = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        mask = np.zeros((self.image_size, self.image_size), np.uint8)
        aliases = {"page": "container", "nav": "sidebar", "navigation": "sidebar"}
        for item in truth.get("components", []):
            kind = aliases.get(item.get("type", "unknown"), item.get("type", "unknown"))
            label = CLASS_TO_IDX.get(kind, CLASS_TO_IDX["unknown"])
            x, y, bw, bh = item["bbox"]
            x1, y1 = int(x / w * self.image_size), int(y / h * self.image_size)
            x2, y2 = int((x + bw) / w * self.image_size), int((y + bh) / h * self.image_size)
            mask[max(0, y1):min(self.image_size, y2), max(0, x1):min(self.image_size, x2)] = label
        # Coarse alignment cues: horizontal/vertical relationships and repeated rows/columns.
        components = truth.get("components", [])
        centers = [((b[0] + b[2] / 2) / w, (b[1] + b[3] / 2) / h)
                   for item in components if (b := item.get("bbox"))]
        xs = np.array([c[0] for c in centers])
        ys = np.array([c[1] for c in centers])
        alignment = torch.tensor([float(len(xs) > 1 and np.std(xs) < .25),
                                  float(len(ys) > 1 and np.std(ys) < .25),
                                  float(len(xs) > 2 and np.ptp(xs) > .5),
                                  float(len(ys) > 2 and np.ptp(ys) > .5)])
        return (torch.from_numpy(image.copy()).unsqueeze(0),
                {"semantic": torch.from_numpy(mask.astype(np.int64)), "alignment": alignment})
