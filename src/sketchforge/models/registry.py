"""Model registry: maps model names to checkpoint paths and metadata.

The registry is a lightweight index. Actual weights are loaded on demand.
Checkpoints live in ``checkpoints/<model_name>/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ModelRegistry:
    """Discovers and tracks checkpoints under the ``checkpoints/`` directory."""

    def __init__(self, checkpoint_root: Path | None = None) -> None:
        from sketchforge.utilities.paths import repo_root

        self._root = checkpoint_root or (repo_root() / "checkpoints")

    # ------------------------------------------------------------------
    def available(self) -> list[str]:
        """Return names of checkpoints that have at least one saved file."""
        if not self._root.is_dir():
            return []
        return [d.name for d in sorted(self._root.iterdir()) if d.is_dir() and any(d.iterdir())]

    def best_checkpoint(self, model_name: str) -> Path | None:
        """Return the ``best.pt`` checkpoint path, or the latest ``.pt`` file."""
        d = self._root / model_name
        if not d.is_dir():
            return None
        best = d / "best.pt"
        if best.is_file():
            return best
        pts = sorted(d.glob("*.pt"))
        return pts[-1] if pts else None

    def metadata(self, model_name: str) -> dict[str, Any]:
        """Load model_metadata.json if it exists, otherwise return an empty dict."""
        meta_file = self._root / model_name / "model_metadata.json"
        if meta_file.is_file():
            return json.loads(meta_file.read_text())
        return {}

    def register_checkpoint(self, model_name: str, checkpoint: Path, meta: dict[str, Any]) -> None:
        """Save metadata alongside a newly saved checkpoint."""
        dest = self._root / model_name
        dest.mkdir(parents=True, exist_ok=True)
        meta_file = dest / "model_metadata.json"
        existing = json.loads(meta_file.read_text()) if meta_file.is_file() else {}
        existing.update(meta)
        meta_file.write_text(json.dumps(existing, indent=2))


# Module-level singleton so callers can do ``from sketchforge.models.registry import REGISTRY``
REGISTRY = ModelRegistry()
