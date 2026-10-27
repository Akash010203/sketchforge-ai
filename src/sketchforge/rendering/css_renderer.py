"""CSS generation for the HTML preview/export.

Each component gets one rule keyed by its stable id, positioned relative to its parent so the DOM
mirrors the Design IR tree and moving a container moves its children.
"""

from __future__ import annotations

from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.schema import Component, ComponentType, DesignDocument
from sketchforge.layout.responsive_rules import responsive_css
from sketchforge.rendering.svg_renderer import BUTTON_PAD, INPUT_PAD, _num

BASE_CSS = """\
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { background: #e5e7eb; }
.sf-page { position: relative; margin: 0 auto; overflow: hidden; }
.sf { position: absolute; margin: 0; padding: 0; }
.sf-text, .sf-heading { white-space: nowrap; overflow: visible; display: flex; align-items: center; }
.sf-button { display: flex; align-items: center; justify-content: center; border: 0; cursor: pointer; white-space: nowrap; }
.sf-input { display: flex; align-items: center; white-space: nowrap; }
.sf-image { background-image: linear-gradient(to top right, transparent calc(50% - 0.5px), #94a3b8 50%, transparent calc(50% + 0.5px)), linear-gradient(to bottom right, transparent calc(50% - 0.5px), #94a3b8 50%, transparent calc(50% + 0.5px)); }
"""


def _color(value: str) -> str:
    if value in ("transparent", "none"):
        return "transparent"
    if len(value) == 9:
        r, g, b, a = (int(value[i : i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r},{g},{b},{_num(a / 255.0)})"
    return value


def rule_for(doc: DesignDocument, comp: Component) -> str:
    parent = doc.get(comp.parent_id) if comp.parent_id else None
    ox = parent.bbox.x if parent else 0.0
    oy = parent.bbox.y if parent else 0.0
    b = comp.bbox
    decl = [
        f"left:{_num(b.x - ox)}px", f"top:{_num(b.y - oy)}px",
        f"width:{_num(b.w)}px", f"height:{_num(b.h)}px",
    ]
    st = comp.style
    if comp.type is not ComponentType.PAGE or st.fill not in ("transparent", "none"):
        decl.append(f"background-color:{_color(st.fill)}")
    if st.stroke not in ("none", "transparent") and st.stroke_width > 0:
        decl.append(f"border:{_num(st.stroke_width)}px solid {_color(st.stroke)}")
    if st.corner_radius:
        radius = "50%" if comp.type is ComponentType.RADIO else f"{_num(min(st.corner_radius, b.w / 2, b.h / 2))}px"
        decl.append(f"border-radius:{radius}")
    if st.opacity < 1.0:
        decl.append(f"opacity:{_num(st.opacity)}")
    if comp.typography is not None:
        t = comp.typography
        decl += [
            f"font-family:{t.font_family}", f"font-size:{_num(t.font_size)}px",
            f"font-weight:{t.font_weight}", f"line-height:{_num(t.line_height)}",
            f"color:{_color(t.color)}",
        ]
        if comp.type is ComponentType.INPUT:
            decl.append(f"padding:0 {_num(INPUT_PAD)}px")
        elif comp.type is ComponentType.BUTTON:
            decl.append(f"padding:0 {_num(BUTTON_PAD)}px")
        elif t.text_align == "center":
            decl.append("justify-content:center")
        elif t.text_align == "right":
            decl.append("justify-content:flex-end")
    return f"#sf-{comp.id} {{ {'; '.join(decl)}; }}"


def render_css(doc: DesignDocument) -> str:
    rules = [BASE_CSS]
    for comp in preorder(doc):
        if comp.id == doc.root_id:
            rules.append(
                f"#sf-{comp.id} {{ width:{_num(doc.page.width)}px; height:{_num(doc.page.height)}px; "
                f"background-color:{_color(doc.page.background)}; }}"
            )
            continue
        rules.append(rule_for(doc, comp))
    rules.append(responsive_css(doc).rstrip())
    return "\n".join(rule for rule in rules if rule) + "\n"
