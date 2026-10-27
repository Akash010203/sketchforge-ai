"""Cleanup: dispose of sandbox temporary directories safely."""
from __future__ import annotations

import shutil
from pathlib import Path


def cleanup_sandbox(path: Path) -> bool:
    """Remove a sandbox directory. Returns True if it was removed."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()
    return True
