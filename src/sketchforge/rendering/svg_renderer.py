"""Deterministic SVG rendering of a Design IR document.

The SVG is what the desktop preview shows (QtSvg) and what reports embed. It is generated purely
from the document, so the same document always yields byte-identical output. Strokes are inset by
half their width so a component's visual outline matches its ``bbox`` exactly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from xml.sax.saxutils import escape, quoteattr

from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.schema import BBox, Component, ComponentType, DesignDocument
from sketchforge.domain.typography import line_box_height

INPUT_PAD = 12.0
BUTTON_PAD = 8.0


def _num(v: float) -> str:
    text = f"{v:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _paint(color: str) -> tuple[str, str | None]:
    """(fill value, opacity) for a hex colour that may carry an alpha channel."""
    if color in ("transparent", "none"):
        return "none", None
    if len(color) == 9:
        return color[:7], _num(int(color[7:9], 16) / 255.0)
    return color, None


def _paint_attrs(prefix: str, color: str) -> str:
    value, opacity = _paint(color)
    out = f' {prefix}="{value}"'
    if opacity is not None:
        out += f' {prefix}-opacity="{opacity}"'
    return out


def inset_box(box: BBox, stroke_width: float) -> tuple[float, float, float, float]:
    half = stroke_width / 2.0
    return box.x + half, box.y + half, max(box.w - stroke_width, 0.5), max(box.h - stroke_width, 0.5)


def effective_radius(comp: Component) -> float:
    return min(comp.style.corner_radius, comp.bbox.w / 2.0, comp.bbox.h / 2.0)


def text_anchor_position(comp: Component) -> tuple[float, float, str]:
    """(x, baseline_y, anchor) for the single line of text a component draws."""
    typo = comp.typography
    assert typo is not None
    box = comp.bbox
    baseline = box.cy + 0.35 * typo.font_size
    if comp.type is ComponentType.BUTTON or typo.text_align == "center":
        return box.cx, baseline, "middle"
    if typo.text_align == "right":
        return box.x2 - (INPUT_PAD if comp.type is ComponentType.INPUT else 0.0), baseline, "end"
    pad = INPUT_PAD if comp.type is ComponentType.INPUT else 0.0
    return box.x + pad, baseline, "start"


def _shape(comp: Component) -> str:
    st, box = comp.style, comp.bbox
    sw = st.stroke_width if st.stroke not in ("none", "transparent") else 0.0
    x, y, w, h = inset_box(box, sw)
    r = max(0.0, effective_radius(comp) - sw / 2.0)
    attrs = _paint_attrs("fill", st.fill) + _paint_attrs("stroke", st.stroke)
    if sw:
        attrs += f' stroke-width="{_num(sw)}"'
    if comp.type is ComponentType.RADIO:
        return (f'<ellipse cx="{_num(box.cx)}" cy="{_num(box.cy)}" rx="{_num(w / 2)}" '
                f'ry="{_num(h / 2)}"{attrs}/>')
    rx = f' rx="{_num(r)}" ry="{_num(r)}"' if r > 0 else ""
    return f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}"{rx}{attrs}/>'


def _text(comp: Component) -> str:
    if not comp.text or comp.typography is None:
        return ""
    typo = comp.typography
    x, y, anchor = text_anchor_position(comp)
    color = typo.color
    value, opacity = _paint(color)
    extra = f' fill-opacity="{opacity}"' if opacity else ""
    family = quoteattr(typo.font_family)
    return (f'<text x="{_num(x)}" y="{_num(y)}" text-anchor="{anchor}" font-family={family} '
            f'font-size="{_num(typo.font_size)}" font-weight="{typo.font_weight}" '
            f'fill="{value}"{extra}>{escape(comp.text)}</text>')


def _image_marks(comp: Component, mark: str = "#94a3b8") -> str:
    b = comp.bbox
    return (f'<path d="M{_num(b.x)} {_num(b.y)}L{_num(b.x2)} {_num(b.y2)}M{_num(b.x2)} {_num(b.y)}'
            f'L{_num(b.x)} {_num(b.y2)}" stroke="{mark}" stroke-width="1" fill="none"/>')


def _component_svg(comp: Component) -> str:
    t = comp.type
    parts: list[str] = []
    if t is ComponentType.PAGE:
        w, h = comp.bbox.w, comp.bbox.h
        parts.append(f'<rect x="0" y="0" width="{_num(w)}" height="{_num(h)}"'
                     f'{_paint_attrs("fill", comp.style.fill)}/>')
    elif t is ComponentType.TEXT or t is ComponentType.HEADING:
        parts.append(_text(comp))
    else:
        parts.append(_shape(comp))
        if t is ComponentType.IMAGE:
            parts.append(_image_marks(comp))
        parts.append(_text(comp))
    body = "".join(p for p in parts if p)
    opacity = f' opacity="{_num(comp.style.opacity)}"' if comp.style.opacity < 1.0 else ""
    label = escape(comp.name or comp.id)
    return (f'<g id="sf-{comp.id}" data-sf-id="{comp.id}" data-sf-type="{t.value}"{opacity}>'
            f'<title>{label}</title>{body}</g>')


def render_svg(
    doc: DesignDocument,
    *,
    selected_ids: Iterable[str] = (),
    highlights: Mapping[str, str] | None = None,
    scale: float = 1.0,
) -> str:
    """Render ``doc`` to an SVG string.

    ``selected_ids`` and ``highlights`` (component id -> colour) draw overlays for the editor and
    for repair reports; they are not part of the design.
    """
    skip: set[str] = set()
    pieces: list[str] = []
    for comp in preorder(doc):
        if comp.parent_id in skip or (comp.parent_id is not None and not doc.require(comp.parent_id).visible):
            skip.add(comp.id)
            continue
        if not comp.visible:
            skip.add(comp.id)
            continue
        pieces.append(_component_svg(comp))
    overlays: list[str] = []
    for cid, color in (highlights or {}).items():
        comp = doc.get(cid)
        if comp is not None:
            b = comp.bbox
            overlays.append(
                f'<rect x="{_num(b.x - 2)}" y="{_num(b.y - 2)}" width="{_num(b.w + 4)}" '
                f'height="{_num(b.h + 4)}" fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-dasharray="6 3"/>')
    for cid in selected_ids:
        comp = doc.get(cid)
        if comp is not None and comp.id != doc.root_id:
            b = comp.bbox
            overlays.append(
                f'<rect x="{_num(b.x - 1)}" y="{_num(b.y - 1)}" width="{_num(b.w + 2)}" '
                f'height="{_num(b.h + 2)}" fill="none" stroke="#f97316" stroke-width="2"/>')
    w, h = doc.page.width, doc.page.height
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(w * scale)}" height="{_num(h * scale)}" '
        f'viewBox="0 0 {_num(w)} {_num(h)}">'
        + "".join(pieces) + "".join(overlays) + "</svg>"
    )


def estimated_text_box_height(comp: Component) -> float:
    typo = comp.typography
    return line_box_height(typo.font_size, typo.line_height) if typo else 0.0
