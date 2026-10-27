"""Shared pytest configuration.

Qt must run on the 'offscreen' platform in CI and on this headless VM, and the variable has to be
set before PySide6 is imported anywhere.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Allow `from tests.support import ...` style helpers and plain `import support`.
sys.path.insert(0, str(Path(__file__).parent))

_HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip ui-marked tests automatically when PySide6 is not installed."""
    skip_ui = pytest.mark.skip(reason="PySide6 not installed — install with: pip install PySide6-Essentials")
    for item in items:
        if "ui" in item.keywords and not _HAS_PYSIDE6:
            item.add_marker(skip_ui)
