"""Device detection: CPU / CUDA / MPS, with safe fallback.

Import this early; it performs no heavy computation.
"""
from __future__ import annotations


def _detect() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


DEVICE: str = _detect()
"""The best available device string: ``'cuda'``, ``'mps'`` or ``'cpu'``."""


def get_device(preferred: str | None = None) -> "torch.device":  # type: ignore[name-defined]
    """Return a ``torch.device`` for ``preferred`` (or the best available)."""
    import torch

    name = preferred or DEVICE
    return torch.device(name)
