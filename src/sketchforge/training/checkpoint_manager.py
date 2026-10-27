"""Checkpoint manager: save, load, and prune model checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import torch


class CheckpointManager:
    """Saves model + optimizer state with metadata and keeps only the best N checkpoints."""

    def __init__(self, directory: Path, keep_best_n: int = 3, mode: str = "min",
                 resume_history: bool = True):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.keep_best_n = keep_best_n
        self.mode = mode          # "min" (loss) or "max" (mAP)
        # A fresh training run must not compare its validation scores to stale weights
        # trained with another split or configuration.
        self._history: list[dict] = self._load_history() if resume_history else []

    # ------------------------------------------------------------------
    def save(
        self,
        model: "torch.nn.Module",
        optimizer: "torch.optim.Optimizer",
        epoch: int,
        metrics: dict[str, float],
        config: dict[str, Any] | None = None,
    ) -> Path:
        """Serialize model + optimizer state and write a metadata file."""
        import torch

        score = (metrics.get("selection_score", metrics.get("mAP@0.25", metrics.get("mAP", 0.0))) if self.mode == "max"
                 else metrics.get("val_loss", metrics.get("loss", 0.0)))
        stem = f"epoch_{epoch:04d}_score_{score:.6f}"
        ckpt_path = self.directory / f"{stem}.pt"
        meta_path = self.directory / f"{stem}.json"

        # Save weights
        torch.save({
            "epoch": epoch,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "metrics": metrics,
            "config": config or {},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, ckpt_path)

        # Hash for integrity
        ckpt_hash = _sha256(ckpt_path)
        meta = {
            "epoch": epoch,
            "score": score,
            "metrics": metrics,
            "path": str(ckpt_path),
            "sha256": ckpt_hash,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        self._history.append(meta)
        best = self.best()
        if (metrics.get("phase") == "val" and best is not None
                and best.get("path") == str(ckpt_path)):
            fd, temp_name = tempfile.mkstemp(prefix="best.", suffix=".tmp", dir=self.directory)
            os.close(fd)
            try:
                shutil.copyfile(ckpt_path, temp_name)
                os.replace(temp_name, self.directory / "best.pt")
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        self._prune()
        self._save_history()
        return ckpt_path

    def best(self) -> dict | None:
        """Return metadata for the best checkpoint, or None if empty."""
        if not self._history:
            return None
        key = "score"
        return min(self._history, key=lambda m: m[key]) if self.mode == "min" \
            else max(self._history, key=lambda m: m[key])

    def load(self, path: Path | None = None) -> dict | None:
        """Load checkpoint state dict from ``path`` (defaults to best)."""
        import torch
        target = path or (Path(self.best()["path"]) if self.best() else None)
        if target is None or not target.exists():
            return None
        return torch.load(str(target), map_location="cpu")

    # ------------------------------------------------------------------
    def _prune(self) -> None:
        if len(self._history) <= self.keep_best_n:
            return
        sorted_h = sorted(
            self._history,
            key=lambda m: m["score"],
            reverse=(self.mode == "max"),
        )
        to_remove = sorted_h[self.keep_best_n:]
        for meta in to_remove:
            p = Path(meta["path"])
            if p.exists():
                p.unlink()
            m = p.with_suffix(".json")
            if m.exists():
                m.unlink()
            self._history.remove(meta)

    def _load_history(self) -> list[dict]:
        h = self.directory / "_history.json"
        if h.exists():
            try:
                return json.loads(h.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_history(self) -> None:
        h = self.directory / "_history.json"
        h.write_text(json.dumps(self._history, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
