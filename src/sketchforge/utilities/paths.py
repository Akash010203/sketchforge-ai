"""Path helpers: repository root discovery and traversal-safe joins."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root (the directory holding pyproject.toml).

    Falls back to the current working directory when the package is installed
    outside a checkout, so the CLI still works from any directory.
    """
    import sys

    # PyInstaller unpacks one-file data into _MEIPASS for the lifetime of the app.
    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and frozen_root:
        return Path(frozen_root)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "sketchforge").is_dir():
            return parent
    return Path.cwd()


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join ``parts`` under ``base`` and refuse anything that escapes ``base``."""
    base_resolved = Path(base).resolve()
    candidate = base_resolved.joinpath(*parts).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise ValueError(f"path escapes base directory: {candidate}")
    return candidate


def _atomic_write(path: str | Path, data: str | bytes, *, binary: bool) -> Path:
    """Write via a sibling temporary file, with a Windows sandbox fallback."""
    import os
    import tempfile

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") if binary else os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        try:
            os.replace(tmp_name, target)
        except PermissionError:
            # Windows package sandboxes can create files but reject sibling renames.
            # The direct write keeps local output working in that environment.
            if binary:
                target.write_bytes(data)  # type: ignore[arg-type]
            else:
                target.write_text(data, encoding="utf-8")  # type: ignore[arg-type]
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    Path(tmp_name).unlink(missing_ok=True)
    return target


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write text atomically when supported by the filesystem."""
    return _atomic_write(path, text, binary=False)


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    """Write bytes atomically when supported by the filesystem."""
    return _atomic_write(path, data, binary=True)
