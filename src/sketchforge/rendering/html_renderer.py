"""HTML rendering: the Design IR tree becomes nested, semantic elements.

Every element carries ``data-sf-id`` so tools can map DOM nodes back to IR components. The output
is plain HTML + CSS (no scripts), safe to open in any browser.
"""

from __future__ import annotations

from html import escape

from sketchforge.design_ir.schema import Component, ComponentType, DesignDocument
from sketchforge.rendering.css_renderer import render_css

_TAG = {
    ComponentType.HEADER: "header", ComponentType.FOOTER: "footer", ComponentType.SIDEBAR: "aside",
    ComponentType.CARD: "section", ComponentType.CONTAINER: "div", ComponentType.HEADING: "h2",
    ComponentType.TEXT: "p", ComponentType.BUTTON: "button", ComponentType.DIVIDER: "div",
    ComponentType.IMAGE: "div", ComponentType.CHECKBOX: "span", ComponentType.RADIO: "span",
    ComponentType.INPUT: "div", ComponentType.UNKNOWN: "div",
}


def _element(doc: DesignDocument, comp: Component) -> str:
    tag = _TAG.get(comp.type, "div")
    attrs = [f'id="sf-{comp.id}"', f'class="sf sf-{comp.type.value}"', f'data-sf-id="{comp.id}"']
    if comp.type is ComponentType.BUTTON:
        attrs.append('type="button"')
    if comp.type is ComponentType.CHECKBOX:
        attrs.append('role="checkbox" aria-checked="false"')
    if comp.type is ComponentType.RADIO:
        attrs.append('role="radio" aria-checked="false"')
    if comp.type is ComponentType.INPUT:
        attrs.append('role="textbox"')
    if comp.type is ComponentType.IMAGE:
        attrs.append('role="img" aria-label="image placeholder"')
    if comp.text_is_inferred:
        attrs.append('data-sf-inferred-text="true"')
    inner = escape(comp.text) if comp.text else ""
    kids = "".join(_element(doc, doc.require(cid)) for cid in doc.children_ids(comp.id)
                   if doc.require(cid).visible)
    return f"<{tag} {' '.join(attrs)}>{inner}{kids}</{tag}>"


def render_html(doc: DesignDocument, *, standalone: bool = True) -> str:
    """Full HTML document (``standalone``) or just the page ``<div>``."""
    root = doc.root
    kids = "".join(_element(doc, doc.require(cid)) for cid in doc.children_ids(root.id)
                   if doc.require(cid).visible)
    page = f'<div id="sf-{root.id}" class="sf-page" data-sf-id="{root.id}">{kids}</div>'
    if not standalone:
        return page
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape(doc.name)}</title>\n<style>\n{render_css(doc)}</style>\n</head>\n"
        f"<body>\n{page}\n</body>\n</html>\n"
    )
