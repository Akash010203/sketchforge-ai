"""Environment manager: prepares the sandbox environment for generated project execution."""
from __future__ import annotations

import shutil
from pathlib import Path


def copy_project_files(source_files: dict[str, str], dest: Path) -> None:
    """Write all text files from a generated project plan into ``dest``."""
    for rel_path, content in source_files.items():
        target = dest / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def has_node() -> bool:
    return shutil.which("node") is not None or shutil.which("node.exe") is not None


def has_npm() -> bool:
    return shutil.which("npm") is not None or shutil.which("npm.cmd") is not None


def has_python() -> bool:
    return shutil.which("python") is not None or shutil.which("python3") is not None


def environment_info() -> dict:
    return {
        "node": shutil.which("node") or shutil.which("node.exe"),
        "npm": shutil.which("npm") or shutil.which("npm.cmd"),
        "python": shutil.which("python") or shutil.which("python3"),
        "npx": shutil.which("npx") or shutil.which("npx.cmd"),
    }
