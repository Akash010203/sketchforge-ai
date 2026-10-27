"""Raster snapshots of a Design IR document without any GUI or browser.

Pillow draws the same primitives the SVG renderer emits (same geometry, same text anchors). This
rasterizer exists for reports, pixel metrics and tests that must run headless; it is *not* a
browser: fonts are Pillow's bundled face, so glyph widths differ from the HTML output. Layout
metrics therefore use geometry and the shared text-width model, not pixels.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.schema import Component, ComponentType, DesignDocument
from sketchforge.rendering.svg_renderer import effective_radius, inset_box, text_anchor_position

SUPERSAMPLE = 2


@lru_cache(maxsize=64)
def _font(size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=max(size_px, 4))


def _rgba(color: str) -> tuple[int, int, int, int] | None:
    if color in ("transparent", "none"):
        return None
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    a = int(color[7:9], 16) if len(color) == 9 else 255
    return r, g, b, a


def _draw_component(draw: ImageDraw.ImageDraw, comp: Component, k: float) -> None:
    st, box = comp.style, comp.bbox
    t = comp.type
    if t is ComponentType.PAGE:
        return
    if t not in (ComponentType.TEXT, ComponentType.HEADING):
        sw = st.stroke_width if st.stroke not in ("none", "transparent") else 0.0
        x, y, w, h = inset_box(box, sw)
        fill, outline = _rgba(st.fill), _rgba(st.stroke)
        xy = (x * k, y * k, (x + w) * k, (y + h) * k)
        width = max(1, round(sw * k)) if sw and outline else 0
        if t is ComponentType.RADIO:
            draw.ellipse(xy, fill=fill, outline=outline, width=width)
        else:
            r = max(0.0, effective_radius(comp) - sw / 2.0) * k
            if r > 0.5:
                draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)
            else:
                draw.rectangle(xy, fill=fill, outline=outline, width=width)
        if t is ComponentType.IMAGE:
            mark = _rgba("#94a3b8")
            draw.line((box.x * k, box.y * k, box.x2 * k, box.y2 * k), fill=mark, width=max(1, round(k)))
            draw.line((box.x2 * k, box.y * k, box.x * k, box.y2 * k), fill=mark, width=max(1, round(k)))
    if comp.text and comp.typography is not None:
        typo = comp.typography
        x, y, anchor = text_anchor_position(comp)
        pil_anchor = {"start": "ls", "middle": "ms", "end": "rs"}[anchor]
        bold = 1 if typo.font_weight >= 600 else 0
        draw.text((x * k, y * k), comp.text, font=_font(round(typo.font_size * k)),
                  fill=_rgba(typo.color), anchor=pil_anchor, stroke_width=bold,
                  stroke_fill=_rgba(typo.color))


def render_image(
    doc: DesignDocument,
    *,
    scale: float = 1.0,
    highlights: Mapping[str, tuple[int, int, int]] | None = None,
) -> np.ndarray:
    """Render to an ``H x W x 3`` uint8 **BGR** array (OpenCV convention)."""
    k = scale * SUPERSAMPLE
    bg = _rgba(doc.page.background) or (255, 255, 255, 255)
    size = (max(1, round(doc.page.width * k)), max(1, round(doc.page.height * k)))
    img = Image.new("RGBA", size, bg)
    draw = ImageDraw.Draw(img, "RGBA")
    hidden: set[str] = set()
    for comp in preorder(doc):
        if not comp.visible or comp.parent_id in hidden:
            hidden.add(comp.id)
            continue
        _draw_component(draw, comp, k)
    for cid, rgb in (highlights or {}).items():
        comp = doc.get(cid)
        if comp is not None:
            b = comp.bbox
            draw.rectangle(((b.x - 2) * k, (b.y - 2) * k, (b.x2 + 2) * k, (b.y2 + 2) * k),
                           outline=(*rgb, 255), width=max(2, round(2 * k)))
    out_size = (max(1, round(doc.page.width * scale)), max(1, round(doc.page.height * scale)))
    small = img.convert("RGB").resize(out_size, Image.LANCZOS)
    return np.asarray(small)[:, :, ::-1].copy()


def render_png_bytes(doc: DesignDocument, *, scale: float = 1.0,
                     highlights: Mapping[str, tuple[int, int, int]] | None = None) -> bytes:
    rgb = render_image(doc, scale=scale, highlights=highlights)[:, :, ::-1]
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG", optimize=False)
    return buf.getvalue()
