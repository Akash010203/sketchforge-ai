"""Training configuration: hyperparameters, paths, and device settings."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrainingConfig:
    # ---- model ---------------------------------------------------------------
    model_name: str = "component_detector_v1"
    num_classes: int = 15          # includes background; matches detector architecture

    # ---- data ----------------------------------------------------------------
    data_dir: str = "datasets/synthetic"
    manifest_path: str = "datasets/manifests/manifest.json"
    train_split: float = 0.7
    val_split: float = 0.15       # test = 1 - train - val
    image_size: int = 512         # square resize target

    # ---- optimiser -----------------------------------------------------------
    epochs: int = 50
    batch_size: int = 16
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    lr_scheduler: str = "cosine"  # "cosine" | "step" | "none"
    lr_step_size: int = 10
    lr_gamma: float = 0.5

    # ---- regularisation ------------------------------------------------------
    dropout: float = 0.1
    label_smoothing: float = 0.05

    # ---- early stopping ------------------------------------------------------
    patience: int = 50            # epochs without val improvement; allows default 50-epoch run
    min_delta: float = 1e-4

    # ---- output --------------------------------------------------------------
    checkpoint_dir: str = "checkpoints"
    save_every_n_epochs: int = 1
    keep_best_n: int = 3

    # ---- determinism ---------------------------------------------------------
    seed: int = 42
    num_workers: int = 4
    pin_memory: bool = True
    mixed_precision: bool = True
    channels_last: bool = True
    prefetch_factor: int = 3

    # ---- device --------------------------------------------------------------
    device: str = "auto"  # "auto" | "cuda" | "cpu" | "mps"

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    def checkpoint_path(self) -> Path:
        return Path(self.checkpoint_dir) / self.model_name

    @classmethod
    def from_yaml(cls, path: str) -> "TrainingConfig":
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
