"""Rendering facade: one place that turns a document into every output format."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import document_hash
from sketchforge.exceptions import RenderError
from sketchforge.rendering.css_renderer import render_css
from sketchforge.rendering.html_renderer import render_html
from sketchforge.rendering.render_snapshot import render_image, render_png_bytes
from sketchforge.rendering.svg_renderer import render_svg
from sketchforge.utilities.paths import atomic_write_bytes, atomic_write_text, ensure_dir


@dataclass(frozen=True)
class RenderedDesign:
    """All renderings of one document state; ``document_hash`` ties them to that state."""

    document_hash: str
    svg: str
    html: str
    css: str
    image: np.ndarray  # BGR uint8

    def save(self, directory: str | Path, stem: str = "design") -> dict[str, Path]:
        out = ensure_dir(directory)
        paths = {
            "svg": out / f"{stem}.svg", "html": out / f"{stem}.html",
            "css": out / f"{stem}.css", "png": out / f"{stem}.png",
        }
        atomic_write_text(paths["svg"], self.svg)
        atomic_write_text(paths["html"], self.html)
        atomic_write_text(paths["css"], self.css)
        import cv2

        ok, buf = cv2.imencode(".png", self.image)
        if not ok:
            raise RenderError("could not encode PNG snapshot")
        atomic_write_bytes(paths["png"], buf.tobytes())
        return paths


def render_all(
    doc: DesignDocument,
    *,
    highlights: Mapping[str, str] | None = None,
) -> RenderedDesign:
    try:
        rgb_highlights = {
            cid: tuple(int(color[i : i + 2], 16) for i in (1, 3, 5)) for cid, color in (highlights or {}).items()
        }
        return RenderedDesign(
            document_hash=document_hash(doc),
            svg=render_svg(doc, highlights=highlights),
            html=render_html(doc),
            css=render_css(doc),
            image=render_image(doc, highlights=rgb_highlights or None),
        )
    except Exception as exc:  # rendering must never take the application down
        raise RenderError(f"render failed: {exc}") from exc


__all__ = ["RenderedDesign", "render_all", "render_html", "render_css", "render_svg",
           "render_image", "render_png_bytes"]
