import pytest
from pydantic import ValidationError

from sketchforge.design_ir import geometry as g
from sketchforge.design_ir.schema import BBox


def box(x, y, w, h):
    return BBox(x=x, y=y, w=w, h=h)


def test_bbox_rejects_non_positive_and_non_finite():
    with pytest.raises(ValueError):
        box(0, 0, 0, 10)
    with pytest.raises(ValueError):
        box(0, 0, 10, -1)
    with pytest.raises(ValueError):
        box(float("nan"), 0, 10, 10)
    with pytest.raises(ValueError):
        box(0, float("inf"), 10, 10)


def test_bbox_is_immutable_and_rounded():
    b = box(0.12345, 1, 10.9999, 5)
    assert b.x == 0.123 and b.w == 11.0
    with pytest.raises(ValidationError):
        b.x = 5  # frozen


def test_intersection_and_iou():
    a, b = box(0, 0, 10, 10), box(5, 5, 10, 10)
    assert g.intersection(a, b) == box(5, 5, 5, 5)
    assert g.iou(a, b) == pytest.approx(25 / 175)
    assert g.iou(a, a) == pytest.approx(1.0)
    assert g.iou(a, box(20, 20, 5, 5)) == 0.0
    assert g.intersection(a, box(10, 0, 5, 5)) is None  # touching edges do not overlap


def test_overlap_ratio_uses_smaller_box():
    big, small = box(0, 0, 100, 100), box(10, 10, 10, 10)
    assert g.overlap_ratio(big, small) == pytest.approx(1.0)
    assert g.iou(big, small) == pytest.approx(0.01)


def test_contains_with_tolerance():
    outer = box(0, 0, 100, 100)
    assert g.contains(outer, box(0, 0, 100, 100))
    assert not g.contains(outer, box(-1, 0, 50, 50))
    assert g.contains(outer, box(-1, 0, 50, 50), tol=1.5)


def test_outside_area_and_ratio():
    outer = box(0, 0, 100, 100)
    inner = box(90, 0, 20, 10)  # half outside
    assert g.outside_area(inner, outer) == pytest.approx(100.0)
    assert g.outside_ratio(inner, outer) == pytest.approx(0.5)
    assert g.outside_ratio(box(10, 10, 5, 5), outer) == 0.0


def test_clamp_into_translates_when_it_fits_and_shrinks_otherwise():
    outer = box(0, 0, 100, 100)
    moved = g.clamp_into(box(90, -5, 20, 20), outer)
    assert moved == box(80, 0, 20, 20)
    shrunk = g.clamp_into(box(-10, -10, 300, 50), outer)
    assert shrunk.w == 100 and shrunk.x == 0 and shrunk.h == 50 and shrunk.y == 0
    assert g.contains(outer, shrunk)


def test_union_and_translate_and_expand():
    assert g.union_bbox([box(0, 0, 10, 10), box(20, 5, 10, 10)]) == box(0, 0, 30, 15)
    assert g.translate(box(1, 2, 3, 4), 10, 20) == box(11, 22, 3, 4)
    assert g.expand(box(10, 10, 10, 10), 2) == box(8, 8, 14, 14)
    with pytest.raises(ValueError):
        g.union_bbox([])


def test_gaps_are_signed():
    a, b = box(0, 0, 10, 10), box(25, 0, 10, 10)
    assert g.horizontal_gap(a, b) == 15
    assert g.horizontal_gap(b, a) == 15
    assert g.horizontal_gap(a, box(5, 0, 10, 10)) == -5  # overlapping
    assert g.vertical_gap(box(0, 0, 10, 10), box(0, 14, 10, 10)) == 4
    assert g.x_overlap(a, box(5, 0, 10, 10)) == 5
    assert g.y_overlap(a, b) == 10


def test_source_to_design_mapping():
    mapped = g.source_to_design(box(110, 60, 40, 20), scale=0.5, offset_x=100, offset_y=50)
    assert mapped == box(5, 5, 20, 10)


def test_edge_values():
    e = g.edge_values(box(10, 20, 30, 40))
    assert e == {"left": 10, "center_x": 25, "right": 40, "top": 20, "center_y": 40, "bottom": 60}


def test_touching_and_sliver_boxes_do_not_crash():
    """Regression: float noise left a ~1e-13 sliver, which BBox rounds to 0 and rejects."""
    from sketchforge.design_ir import BBox
    from sketchforge.design_ir.geometry import intersection, intersection_area

    a = BBox(x=115.882, y=561.488, w=100, h=24.6)
    b = BBox(x=119.757, y=586.088 + 1.1368683772161603e-13, w=50, h=20)
    assert intersection(a, b) is None and intersection_area(a, b) == 0.0 or intersection_area(a, b) < 1e-9
    assert intersection_area(BBox(x=0, y=0, w=10, h=10), BBox(x=10, y=0, w=5, h=5)) == 0.0
    assert intersection_area(BBox(x=0, y=0, w=10, h=10), BBox(x=5, y=5, w=10, h=10)) == 25.0
