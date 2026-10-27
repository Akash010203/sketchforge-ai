"""Load generated sketch/annotation pairs for detector training."""
from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np

from sketchforge.training.config import TrainingConfig
from sketchforge.training.seed import seed_everything


class ComponentDetectorDataset:
    """Disk-backed PNG/JSON dataset with independently configured augmentation."""

    def __init__(self, data_dir: str | Path, image_size: int, train: bool = False):
        self.root = Path(data_dir)
        self.image_size = image_size
        self.train = train
        self.pairs = [(p, p.with_suffix(".json")) for p in sorted(self.root.glob("*.png"))
                      if p.with_suffix(".json").is_file()]
        if not self.pairs:
            return

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, index):
        import cv2
        import torch
        from sketchforge.models.component_detector.dataset import truth_to_targets

        image_path, label_path = self.pairs[index]
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"Could not read image: {image_path}")
        truth = json.loads(label_path.read_text(encoding="utf-8"))
        h, w = bgr.shape[:2]
        size = self.image_size
        bgr = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        image = 1.0 - gray
        boxes, labels = truth_to_targets(truth, w, h)
        if self.train:
            if random.random() < 0.3:
                image = image[:, ::-1].copy()
                boxes = [(1.0 - cx, cy, bw, bh) for cx, cy, bw, bh in boxes]
            gain = random.uniform(0.8, 1.2)
            image = np.clip(image * gain, 0.0, 1.0)
            # Apply one projective transform to both pixels and box corners.
            angle = random.uniform(-5.0, 5.0)
            affine = cv2.getRotationMatrix2D((size / 2.0, size / 2.0), angle,
                                             random.uniform(0.97, 1.03))
            matrix = np.vstack((affine, [0.0, 0.0, 1.0])).astype(np.float32)
            if random.random() < 0.5:
                corners = np.float32([[0, 0], [size, 0], [size, size], [0, size]])
                jitter = size * 0.025
                warped = corners + np.random.uniform(-jitter, jitter, corners.shape).astype(np.float32)
                matrix = cv2.getPerspectiveTransform(corners, warped) @ matrix
            image = cv2.warpPerspective(image, matrix, (size, size), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
            transformed, transformed_labels = [], []
            for (cx, cy, bw, bh), label in zip(boxes, labels):
                points = np.float32([
                    [(cx - bw / 2) * size, (cy - bh / 2) * size],
                    [(cx + bw / 2) * size, (cy - bh / 2) * size],
                    [(cx + bw / 2) * size, (cy + bh / 2) * size],
                    [(cx - bw / 2) * size, (cy + bh / 2) * size],
                ]).reshape(-1, 1, 2)
                points = cv2.perspectiveTransform(points, matrix).reshape(-1, 2)
                x1, y1 = np.maximum(points.min(axis=0), 0.0)
                x2, y2 = np.minimum(points.max(axis=0), float(size))
                if x2 > x1 and y2 > y1:
                    transformed.append(((x1 + x2) / (2 * size), (y1 + y2) / (2 * size),
                                        (x2 - x1) / size, (y2 - y1) / size))
                    transformed_labels.append(label)
            boxes = transformed
            labels = transformed_labels
            # Mild morphology varies stroke weight without changing annotations.
            if random.random() < 0.5:
                kernel = np.ones((random.choice((2, 3)),) * 2, np.uint8)
                mask = (image * 255).astype(np.uint8)
                morphology = cv2.dilate if random.random() < 0.5 else cv2.erode
                image = morphology(mask, kernel, iterations=1).astype(np.float32) / 255.0
        return torch.from_numpy(image.copy()).unsqueeze(0), {
            "boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def _collate(batch):
    import torch
    images, targets = zip(*batch)
    return torch.stack(images), list(targets)


def make_loaders(cfg: TrainingConfig):
    """Return train, validation and test loaders without shared transform state."""
    try:
        import torch
        from torch.utils.data import DataLoader, Subset
    except ImportError as e:
        raise ImportError("PyTorch is required for training. Install torch.") from e

    seed_everything(cfg.seed)
    base = ComponentDetectorDataset(cfg.data_dir, cfg.image_size)
    n = len(base)
    if n == 0:
        raise RuntimeError(f"No PNG/JSON pairs found in {cfg.data_dir}. Generate data first.")
    groups: dict[str, list[int]] = {}
    for index, (_, label_path) in enumerate(base.pairs):
        try:
            layout = json.loads(label_path.read_text(encoding="utf-8")).get("layout", "unknown")
        except (OSError, json.JSONDecodeError):
            layout = "unknown"
        groups.setdefault(str(layout), []).append(index)
    if len(groups) >= 3:
        names = sorted(groups)
        random.Random(cfg.seed).shuffle(names)
        n_val_groups = max(1, round(len(names) * cfg.val_split))
        n_test_groups = max(1, round(len(names) * (1 - cfg.train_split - cfg.val_split)))
        if n_val_groups + n_test_groups >= len(names):
            n_val_groups = n_test_groups = 1
        val_names = set(names[:n_val_groups])
        test_names = set(names[n_val_groups:n_val_groups + n_test_groups])
        train_names = set(names) - val_names - test_names
        splits = tuple([i for name in chosen for i in groups[name]]
                       for chosen in (train_names, val_names, test_names))
        print(f"[dataloader] split by layout: train={sorted(train_names)} "
              f"val={sorted(val_names)} test={sorted(test_names)}")
    else:
        indices = torch.randperm(n, generator=torch.Generator().manual_seed(cfg.seed)).tolist()
        n_train = max(1, int(n * cfg.train_split)) if n >= 3 else n
        n_val = max(1, int(n * cfg.val_split)) if n - n_train >= 2 else max(0, n - n_train - 1)
        splits = (indices[:n_train], indices[n_train:n_train+n_val], indices[n_train+n_val:])
    loaders = []
    for split, training in zip(splits, (True, False, False)):
        ds = ComponentDetectorDataset(cfg.data_dir, cfg.image_size, train=training)
        loader = DataLoader(Subset(ds, split), batch_size=cfg.batch_size,
                            shuffle=training, num_workers=cfg.num_workers,
                            pin_memory=cfg.pin_memory and cfg.resolve_device() == "cuda",
                            collate_fn=_collate, drop_last=False,
                            persistent_workers=cfg.num_workers > 0,
                            prefetch_factor=cfg.prefetch_factor if cfg.num_workers > 0 else None)
        loaders.append(loader)
    return tuple(loaders)
