"""Own-model training and inference (Phase 6).

Phase-6 modules live here: component detector architecture, dataset loading, training, inference.
Until PyTorch training begins, this package exports only the registry and device probe so the rest
of the application can import without requiring torch.
"""
from __future__ import annotations

from sketchforge.models.registry import ModelRegistry

__all__ = ["ModelRegistry"]
