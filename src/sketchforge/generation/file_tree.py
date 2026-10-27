"""File tree: materialise a ProjectPlan onto disk.

Writes files atomically (temp + rename) into an isolated output directory.
Validates the target directory is not the SketchForge source tree.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from sketchforge.generation.project_planner import ProjectPlan, PlannedFile
from sketchforge.utilities.paths import repo_root


class FileTreeError(RuntimeError):
    pass


def _safe_root(target: Path) -> Path:
    """Ensure we never accidentally write into the SketchForge source tree."""
    target = target.resolve()
    repo = repo_root().resolve()
    if str(target).startswith(str(repo / "src")):
        raise FileTreeError(f"Refusing to write generated project into the source tree: {target}")
    return target


def materialise(plan: ProjectPlan, target: Path) -> dict[str, int]:
    """Write every PlannedFile in ``plan`` into ``target``.

    Returns a dict of {relative_path: byte_count} for all written files.
    """
    from sketchforge.generation.frontend.project_export import render_file

    root = _safe_root(target)
    root.mkdir(parents=True, exist_ok=True)

    # Create declared directory roots
    for d in plan.directory_roots:
        (root / d).mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    for pf in plan.files:
        content = render_file(pf, plan)
        if content is None:
            continue
        dest = root / pf.relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(dest, content)
        written[pf.relative_path] = len(content.encode())

    return written


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    shutil.move(str(tmp), str(path))


def tree_summary(root: Path) -> list[str]:
    """Return a sorted list of all files inside ``root`` (relative POSIX paths)."""
    root = root.resolve()
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
    )
