"""What the service says about its models: ids, modalities, and what we may rely on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sketchforge.integrations.nvidia.model_configuration import is_nvidia_model


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    modality: str | None  # e.g. "text->text"; None when the service did not say
    context_length: int | None = None

    @property
    def is_nvidia(self) -> bool:
        return is_nvidia_model(self.model_id)

    @property
    def accepts_images(self) -> bool | None:
        """True/False when the modality string says so, None when unknown (treat as False)."""
        if self.modality is None:
            return None
        return "image" in self.modality.split("->")[0]


def parse_models(raw: list[dict[str, Any]]) -> list[ModelInfo]:
    """Tolerant parser for ``GET /v1/models?verbose=true`` items; unknown fields are ignored."""
    out: list[ModelInfo] = []
    for item in raw:
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        modality = arch.get("modality") if isinstance(arch.get("modality"), str) else None
        ctx = item.get("context_length", arch.get("context_length"))
        out.append(ModelInfo(model_id, modality, int(ctx) if isinstance(ctx, (int, float)) else None))
    return sorted(out, key=lambda m: m.model_id)


def nvidia_models(models: list[ModelInfo]) -> list[ModelInfo]:
    return [m for m in models if m.is_nvidia]


def pick_model(models: list[ModelInfo], preferred: list[str]) -> ModelInfo | None:
    """First preferred id that the service actually lists; None if none is available."""
    by_id = {m.model_id: m for m in models}
    return next((by_id[p] for p in preferred if p in by_id), None)
