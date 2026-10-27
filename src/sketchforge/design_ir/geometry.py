"""Pure box geometry on :class:`BBox`. No I/O, no OpenCV, fully unit-testable."""

from __future__ import annotations

from collections.abc import Iterable

from sketchforge.design_ir.schema import BBox

_MIN_EXTENT = 1e-3  # BBox rounds to 3 decimals; anything thinner cannot be represented as a box


def intersection(a: BBox, b: BBox) -> BBox | None:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x2, b.x2), min(a.y2, b.y2)
    if x2 - x1 < _MIN_EXTENT or y2 - y1 < _MIN_EXTENT:
        return None
    return BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def intersection_area(a: BBox, b: BBox) -> float:
    """Overlap area computed from raw floats (no box is constructed, so slivers are fine)."""
    w = min(a.x2, b.x2) - max(a.x, b.x)
    h = min(a.y2, b.y2) - max(a.y, b.y)
    return w * h if w > 0 and h > 0 else 0.0


def union_bbox(boxes: Iterable[BBox]) -> BBox:
    items = list(boxes)
    if not items:
        raise ValueError("union_bbox needs at least one box")
    x1 = min(b.x for b in items)
    y1 = min(b.y for b in items)
    x2 = max(b.x2 for b in items)
    y2 = max(b.y2 for b in items)
    return BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def iou(a: BBox, b: BBox) -> float:
    inter = intersection_area(a, b)
    if inter == 0.0:
        return 0.0
    return inter / (a.area + b.area - inter)


def overlap_ratio(a: BBox, b: BBox) -> float:
    """Intersection divided by the *smaller* box area (1.0 when one box sits inside the other)."""
    inter = intersection_area(a, b)
    if inter == 0.0:
        return 0.0
    return inter / min(a.area, b.area)


def contains(outer: BBox, inner: BBox, tol: float = 0.0) -> bool:
    return (
        inner.x >= outer.x - tol
        and inner.y >= outer.y - tol
        and inner.x2 <= outer.x2 + tol
        and inner.y2 <= outer.y2 + tol
    )


def outside_area(inner: BBox, outer: BBox) -> float:
    """Area of ``inner`` that lies outside ``outer``."""
    return inner.area - intersection_area(inner, outer)


def outside_ratio(inner: BBox, outer: BBox) -> float:
    return outside_area(inner, outer) / inner.area


def translate(box: BBox, dx: float, dy: float) -> BBox:
    return BBox(x=box.x + dx, y=box.y + dy, w=box.w, h=box.h)


def with_position(box: BBox, x: float | None = None, y: float | None = None) -> BBox:
    return BBox(x=box.x if x is None else x, y=box.y if y is None else y, w=box.w, h=box.h)


def with_size(box: BBox, w: float | None = None, h: float | None = None) -> BBox:
    return BBox(x=box.x, y=box.y, w=box.w if w is None else w, h=box.h if h is None else h)


def expand(box: BBox, amount: float) -> BBox:
    return BBox(
        x=box.x - amount, y=box.y - amount, w=box.w + 2 * amount, h=box.h + 2 * amount
    )


def scale_about_origin(box: BBox, sx: float, sy: float | None = None) -> BBox:
    sy = sx if sy is None else sy
    return BBox(x=box.x * sx, y=box.y * sy, w=box.w * sx, h=box.h * sy)


def source_to_design(box: BBox, scale: float, offset_x: float, offset_y: float) -> BBox:
    """Map a source-image box into design space: ``(source - offset) * scale``."""
    return BBox(
        x=(box.x - offset_x) * scale,
        y=(box.y - offset_y) * scale,
        w=box.w * scale,
        h=box.h * scale,
    )


def clamp_into(inner: BBox, outer: BBox) -> BBox:
    """Smallest change that places ``inner`` inside ``outer``.

    Translates when the box fits; shrinks (keeping the top-left clamped) when it is larger than
    ``outer`` in that dimension.
    """
    w = min(inner.w, outer.w)
    h = min(inner.h, outer.h)
    x = min(max(inner.x, outer.x), outer.x2 - w)
    y = min(max(inner.y, outer.y), outer.y2 - h)
    return BBox(x=x, y=y, w=w, h=h)


def x_overlap(a: BBox, b: BBox) -> float:
    return max(0.0, min(a.x2, b.x2) - max(a.x, b.x))


def y_overlap(a: BBox, b: BBox) -> float:
    return max(0.0, min(a.y2, b.y2) - max(a.y, b.y))


def horizontal_gap(a: BBox, b: BBox) -> float:
    """Signed horizontal distance between facing edges (negative when the boxes overlap in x)."""
    if a.x <= b.x:
        return b.x - a.x2
    return a.x - b.x2


def vertical_gap(a: BBox, b: BBox) -> float:
    if a.y <= b.y:
        return b.y - a.y2
    return a.y - b.y2


def edge_values(box: BBox) -> dict[str, float]:
    """The six alignment-relevant coordinates of a box."""
    return {
        "left": box.x,
        "center_x": box.cx,
        "right": box.x2,
        "top": box.y,
        "center_y": box.cy,
        "bottom": box.y2,
    }
