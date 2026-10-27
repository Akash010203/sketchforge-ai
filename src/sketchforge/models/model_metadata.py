"""Model metadata: structured record of a trained model's provenance and performance."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelMetadata:
    model_name: str
    architecture: str
    num_classes: int
    num_parameters: int = 0
    dataset: str = "synthetic"
    train_samples: int = 0
    val_samples: int = 0
    test_samples: int = 0
    best_epoch: int = 0
    best_val_loss: float = float("inf")
    test_accuracy: float = 0.0
    test_mAP: float = 0.0
    test_mean_iou: float = 0.0
    # Comparison against deterministic baseline
    baseline_f1: float = 0.0
    trained_f1: float = 0.0
    training_device: str = "unknown"
    training_duration_s: float = 0.0
    checkpoint_path: str = ""
    checkpoint_sha256: str = ""
    config: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ModelMetadata":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_markdown(self) -> str:
        return f"""\
# Model Card: {self.model_name}

| | |
|---|---|
| Architecture | {self.architecture} |
| Classes | {self.num_classes} |
| Parameters | {self.num_parameters:,} |
| Dataset | {self.dataset} ({self.train_samples} train / {self.val_samples} val / {self.test_samples} test) |
| Training device | {self.training_device} |
| Training duration | {self.training_duration_s:.0f} s |
| Best epoch | {self.best_epoch} |
| Best val loss | {self.best_val_loss:.6f} |
| Test accuracy | {self.test_accuracy:.4f} |
| Test mAP | {self.test_mAP:.4f} |
| Test mean IoU | {self.test_mean_iou:.4f} |
| Heuristic baseline F1 | {self.baseline_f1:.4f} |
| Trained model F1 | {self.trained_f1:.4f} |
| Checkpoint | `{self.checkpoint_path}` |
| SHA-256 | `{self.checkpoint_sha256}` |
| Created | {self.created_at} |

## Limitations

{''.join(f"- {l}{chr(10)}" for l in self.limitations) if self.limitations else "_None recorded_"}
"""
