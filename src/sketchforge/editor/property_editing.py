"""Property-name based editing: what the properties panel and natural-language edits call.

``make_edit(doc, component_id, prop, value)`` turns a property name and a user-supplied value
into a validated :class:`Command`. Values may be strings (as typed in a text field); they are
parsed and range-checked here, so the UI never builds IR objects itself.
"""

from __future__ import annotations

import re
from typing import Any

from sketchforge.design_ir.geometry import clamp_into
from sketchforge.design_ir.schema import BBox, DesignDocument
from sketchforge.editor.design_commands import (
    Command,
    MoveCommand,
    RenameCommand,
    SetBBoxCommand,
    SetStyleCommand,
    SetTextCommand,
    SetTypographyCommand,
    SetVisibleCommand,
)
from sketchforge.exceptions import EditError

_HEX3 = re.compile(r"^#([0-9a-fA-F])([0-9a-fA-F])([0-9a-fA-F])$")

EDITABLE_PROPERTIES = (
    "text", "name", "x", "y", "width", "height", "fill", "stroke", "stroke_width",
    "corner_radius", "opacity", "color", "font_size", "font_weight", "text_align", "visible",
)


def parse_color(value: Any) -> str:
    text = str(value).strip().lower()
    m = _HEX3.match(text)
    if m:
        text = "#" + "".join(ch * 2 for ch in m.groups())
    if text in ("transparent", "none") or re.fullmatch(r"#(?:[0-9a-f]{6}|[0-9a-f]{8})", text):
        return text
    raise EditError(f"'{value}' is not a colour; use #rrggbb, #rgb, 'transparent' or 'none'")


def _number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EditError(f"{name} must be a number, got {value!r}") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise EditError(f"{name} must be finite")
    return number


def make_edit(doc: DesignDocument, component_id: str, prop: str, value: Any) -> Command:
    comp = doc.get(component_id)
    if comp is None:
        raise EditError(f"no component {component_id!r}")
    if prop == "text":
        return SetTextCommand(component_id, None if value in (None, "") else str(value))
    if prop == "name":
        return RenameCommand(component_id, str(value))
    if prop == "visible":
        return SetVisibleCommand(component_id, bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes", "on"))
    if prop in ("x", "y"):
        target = _number(value, prop)
        dx = target - comp.bbox.x if prop == "x" else 0.0
        dy = target - comp.bbox.y if prop == "y" else 0.0
        return MoveCommand(component_id, round(dx, 3), round(dy, 3), reason=f"set {prop} of {component_id} to {target:g}")
    if prop in ("width", "height"):
        size = _number(value, prop)
        if size <= 0:
            raise EditError(f"{prop} must be greater than 0")
        b = comp.bbox
        box = BBox(x=b.x, y=b.y, w=size if prop == "width" else b.w, h=size if prop == "height" else b.h)
        return SetBBoxCommand(component_id, box, reason=f"set {prop} of {component_id} to {size:g}")
    if prop in ("fill", "stroke"):
        return SetStyleCommand(component_id, **{prop: parse_color(value)})
    if prop in ("stroke_width", "corner_radius", "opacity"):
        return SetStyleCommand(component_id, **{prop: _number(value, prop)})
    if prop == "color":
        return SetTypographyCommand(component_id, color=parse_color(value))
    if prop == "font_size":
        return SetTypographyCommand(component_id, font_size=_number(value, prop))
    if prop == "font_weight":
        return SetTypographyCommand(component_id, font_weight=int(_number(value, prop)))
    if prop == "text_align":
        return SetTypographyCommand(component_id, text_align=str(value))
    raise EditError(f"unknown property {prop!r}; editable: {', '.join(EDITABLE_PROPERTIES)}")


def fit_inside_parent(doc: DesignDocument, component_id: str) -> BBox:
    """The nearest box that keeps a component inside its parent (used by drag handling)."""
    comp = doc.require(component_id)
    if comp.parent_id is None:
        return comp.bbox
    return clamp_into(comp.bbox, doc.require(comp.parent_id).bbox)
