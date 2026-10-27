"""Hand-built documents for tests (no vision pipeline involved, fully deterministic)."""

from __future__ import annotations

from sketchforge.design_ir import (
    BBox,
    Component,
    ComponentType,
    DesignDocument,
    LayoutSpec,
    Style,
    Typography,
    add_component,
    new_document,
)
from sketchforge.rendering.theme_engine import DEFAULT_THEME as T


def _c(cid, parent, ctype, x, y, w, h, text=None, font=16.0, **kw):
    typo = T.typography_for(ctype, font) if text is not None or ctype in (
        ComponentType.TEXT, ComponentType.HEADING, ComponentType.BUTTON, ComponentType.INPUT) else None
    layout = LayoutSpec(mode="absolute") if ctype in (
        ComponentType.HEADER, ComponentType.CARD, ComponentType.CONTAINER) else None
    return Component(
        id=cid, type=ctype, parent_id=parent, bbox=BBox(x=x, y=y, w=w, h=h), text=text,
        typography=typo, style=T.style_for(ctype), layout=layout, **kw,
    )


def make_form_document() -> DesignDocument:
    """A tidy sign-up form: header, a card with a heading, four evenly spaced inputs and a button.

    Everything is aligned (left edge x=130) and the inputs have a uniform 60 px pitch, so the
    document has no layout issues until a test injects one.
    """
    d = new_document("form", 600, 600, document_id="doc-form")
    add_component(d, _c("header-1", "page", ComponentType.HEADER, 0, 0, 600, 60))
    add_component(d, _c("text-1", "header-1", ComponentType.TEXT, 24, 20, 120, 20, "Acme", 16))
    add_component(d, _c("card-1", "page", ComponentType.CARD, 100, 100, 400, 460))
    add_component(d, _c("heading-1", "card-1", ComponentType.HEADING, 130, 120, 200, 32, "Sign up", 22))
    for i in range(4):
        add_component(d, _c(f"input-{i + 1}", "card-1", ComponentType.INPUT, 130, 170 + 60 * i, 340, 44,
                            f"Field {i + 1}", 16))
    add_component(d, _c("button-1", "card-1", ComponentType.BUTTON, 130, 440, 340, 48, "Submit", 16))
    return d


__all__ = ["make_form_document", "Style", "Typography"]
