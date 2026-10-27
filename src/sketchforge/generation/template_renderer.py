"""Small, dependency-free renderer for packaged text templates."""
from __future__ import annotations

from pathlib import Path
from string import Template


_TEMPLATE_DIR = Path(__file__).with_name("templates")


def render_template(name: str, **values: str) -> str:
    """Render a package template using ``$name`` placeholders."""
    path = _TEMPLATE_DIR / name
    if path.parent != _TEMPLATE_DIR or not path.is_file():
        raise FileNotFoundError(f"Generation template not found: {name}")
    return Template(path.read_text(encoding="utf-8")).substitute(values)
