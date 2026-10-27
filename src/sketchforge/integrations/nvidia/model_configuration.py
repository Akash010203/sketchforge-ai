"""Eligible NVIDIA open-source models and what is (not) known about them.

Provenance matters here: an identifier appearing in a vendor notice is not proof that the model is
currently served or what it accepts. ``verified_live`` stays False until ``scripts/verify_nebius.py``
has listed it from the real service.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NvidiaModel:
    model_id: str
    family: str
    source: str  # where the identifier was read
    image_input: bool | None  # None = unknown
    verified_live: bool = False
    note: str = ""


CATALOGUE: tuple[NvidiaModel, ...] = (
    NvidiaModel(
        "nvidia/Nemotron-3_5-Lightning", "Nemotron", "Nebius August-2026 deprecation notice (named replacement)",
        None, note="image input not stated in the pages read; treated as text-only until verified"),
    NvidiaModel(
        "nvidia/nemotron-3-super-120b-a12b", "Nemotron", "Nebius August-2026 deprecation notice (named replacement)",
        None, note="image input not stated in the pages read; treated as text-only until verified"),
)


def find(model_id: str) -> NvidiaModel | None:
    return next((m for m in CATALOGUE if m.model_id == model_id), None)


def is_nvidia_model(model_id: str) -> bool:
    return model_id.lower().startswith("nvidia/")
