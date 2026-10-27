"""Dataset license policy helpers and manifest loader."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from sketchforge.datasets.manifest_schema import DatasetManifest, license_audit


def load_manifest(path: str | Path) -> DatasetManifest:
    """Load and validate a JSON dataset manifest."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read JSON manifest {path}: {exc}") from exc
    try:
        return DatasetManifest.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


__all__ = ["license_audit", "load_manifest"]
