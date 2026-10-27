"""Deterministic JSON (de)serialization of Design IR documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sketchforge.design_ir.migrations import migrate_to_current
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.exceptions import DesignValidationError
from sketchforge.utilities.hashing import canonical_hash
from sketchforge.utilities.paths import atomic_write_text


def to_dict(doc: DesignDocument) -> dict[str, Any]:
    return doc.model_dump(mode="json")


def to_json(doc: DesignDocument, indent: int | None = 2) -> str:
    """Field order follows the schema, so identical documents give identical text."""
    return json.dumps(to_dict(doc), indent=indent, ensure_ascii=False) + "\n"


def from_dict(data: dict[str, Any]) -> DesignDocument:
    migrated = migrate_to_current(data)
    try:
        return DesignDocument.model_validate(migrated)
    except ValidationError as exc:
        raise DesignValidationError(f"document does not match the Design IR schema: {exc}") from exc


def from_json(text: str) -> DesignDocument:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DesignValidationError(f"not valid JSON: {exc}") from exc
    return from_dict(data)


def save_document(doc: DesignDocument, path: str | Path) -> Path:
    return atomic_write_text(path, to_json(doc))


def load_document(path: str | Path) -> DesignDocument:
    return from_json(Path(path).read_text(encoding="utf-8"))


def document_hash(doc: DesignDocument) -> str:
    """Stable content hash: equal documents hash equally across runs and machines."""
    return canonical_hash(to_dict(doc))
