"""Model checkpointing utilities: save, load, hash, and metadata helpers."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def save_checkpoint(
    model: "torch.nn.Module",
    optimizer: "torch.optim.Optimizer | None",
    epoch: int,
    metrics: dict,
    path: Path,
    config: dict | None = None,
) -> str:
    """Save a checkpoint and return its SHA-256 (first 16 hex chars)."""
    import torch
    state = {
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict() if optimizer else None,
        "metrics": metrics,
        "config": config or {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(state, str(path))
    return _sha256(path)


def load_checkpoint(path: Path, device: str = "cpu") -> dict:
    """Load a checkpoint dict from disk."""
    import torch
    return torch.load(str(path), map_location=device)


def checkpoint_metadata(path: Path) -> dict:
    """Return lightweight metadata without loading model weights."""
    meta_path = path.with_suffix(".json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
