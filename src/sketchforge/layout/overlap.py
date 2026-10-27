"""Shallow overlaps ("slivers") between neighbouring boxes.

Detected boxes include pen width and the loose margins around handwriting, so a label drawn right
next to a checkbox routinely overlaps it by a few pixels. Such a sliver is not a design decision;
trimming the overlapping side of the more flexible box removes it without moving anything, which
keeps every alignment line intact.
"""

from __future__ import annotations

from sketchforge.design_ir.geometry import intersection
from sketchforge.design_ir.schema import BBox, Component, ComponentType

SLIVER_PX = 8.0  # overlaps shallower than this count as slivers
GAP_PX = 1.0     # clearance left between the trimmed box and its neighbour
_TEXT_LIKE = {ComponentType.TEXT, ComponentType.HEADING}


def sliver_trim(a: Component, b: Component) -> tuple[Component, BBox] | None:
    """(component to trim, its trimmed box) when ``a`` and ``b`` overlap only shallowly."""
    inter = intersection(a.bbox, b.bbox)
    if inter is None or min(inter.w, inter.h) > SLIVER_PX:
        return None
    a_text, b_text = a.type in _TEXT_LIKE, b.type in _TEXT_LIKE
    if a_text != b_text:  # text boxes are loose bounds around scribble; controls keep their shape
        victim, other = (a, b) if a_text else (b, a)
    else:
        victim, other = (a, b) if a.bbox.area >= b.bbox.area else (b, a)
    vb, ob = victim.bbox, other.bbox
    if inter.w <= inter.h:
        if vb.cx >= ob.cx:
            x = ob.x2 + GAP_PX
            new = BBox(x=x, y=vb.y, w=vb.x2 - x, h=vb.h)
        else:
            new = BBox(x=vb.x, y=vb.y, w=ob.x - GAP_PX - vb.x, h=vb.h)
    else:
        if vb.cy >= ob.cy:
            y = ob.y2 + GAP_PX
            new = BBox(x=vb.x, y=y, w=vb.w, h=vb.y2 - y)
        else:
            new = BBox(x=vb.x, y=vb.y, w=vb.w, h=ob.y - GAP_PX - vb.y)
    except_small = new.w < 4 or new.h < 4 or new.area < 0.7 * vb.area
    return None if except_small else (victim, new)
