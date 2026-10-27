"""Project folder layout and IO.

    <project>/
      project.json          name, format version, source image hash
      design.json           the Design IR document (deterministic JSON)
      source/<sketch file>  the original image, byte-for-byte
      renders/              svg / html / css / png of the saved design
      reports/              repair report(s)

Everything is plain files. Writes are atomic (temp file + rename), names are sanitised and every
path is checked to stay inside the project folder.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import load_document, save_document
from sketchforge.exceptions import SketchForgeError
from sketchforge.utilities.paths import atomic_write_bytes, atomic_write_text, ensure_dir, safe_join

PROJECT_FORMAT = 1
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class ProjectStoreError(SketchForgeError):
    """A project folder is missing, malformed or unsafe to read."""


@dataclass(frozen=True)
class ProjectMeta:
    name: str
    source_file: str | None = None
    source_sha256: str | None = None


def sanitize_filename(name: str, default: str = "sketch") -> str:
    cleaned = _NAME_RE.sub("_", Path(name).name).strip("._") or default
    return cleaned[:80]


def save_project(
    directory: str | Path,
    document: DesignDocument,
    meta: ProjectMeta,
    source_bytes: bytes | None = None,
) -> Path:
    root = ensure_dir(directory)
    source_file = meta.source_file
    if source_bytes is not None and source_file:
        source_file = sanitize_filename(source_file)
        atomic_write_bytes(safe_join(ensure_dir(root / "source"), source_file), source_bytes)
    atomic_write_text(
        safe_join(root, "project.json"),
        json.dumps({"format": PROJECT_FORMAT, "name": meta.name, "source_file": source_file,
                    "source_sha256": meta.source_sha256}, indent=2, sort_keys=True),
    )
    save_document(document, safe_join(root, "design.json"))
    ensure_dir(root / "renders")
    ensure_dir(root / "reports")
    return root


def load_project(directory: str | Path) -> tuple[DesignDocument, ProjectMeta, bytes | None]:
    root = Path(directory)
    meta_path = root / "project.json"
    if not meta_path.is_file():
        raise ProjectStoreError(f"{root} is not a SketchForge project (no project.json)")
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectStoreError(f"project.json is not valid JSON: {exc}") from exc
    if raw.get("format") != PROJECT_FORMAT:
        raise ProjectStoreError(f"unsupported project format {raw.get('format')!r}")
    meta = ProjectMeta(str(raw.get("name", root.name)), raw.get("source_file"), raw.get("source_sha256"))
    doc = load_document(safe_join(root, "design.json"))
    source: bytes | None = None
    if meta.source_file:
        candidate = safe_join(root, "source", sanitize_filename(meta.source_file))
        if candidate.is_file():
            source = candidate.read_bytes()
    return doc, meta, source


def copy_into(directory: str | Path, relative: str, source: Path) -> Path:
    dest = safe_join(ensure_dir(directory), relative)
    ensure_dir(dest.parent)
    shutil.copyfile(source, dest)
    return dest
