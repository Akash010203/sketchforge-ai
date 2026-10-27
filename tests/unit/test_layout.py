import pytest

from sketchforge.design_ir import ComponentType, LayoutConstraints, move_subtree, validate_document
from sketchforge.layout.alignment import alignment_moves, apply_alignment
from sketchforge.layout.design_refinement import (
    BuildReport,
    enforce_containment,
    infer_container_layout,
    refine_document,
)
from sketchforge.layout.grouping import (
    find_misalignments,
    repeated_groups,
    robust_pitch_fit,
)
from sketchforge.layout.spacing import apply_spacing, spacing_moves
from support import make_form_document

RADIUS, TOL = 16.0, 2.0


@pytest.fixture
def doc():
    return make_form_document()


def test_clean_form_has_no_alignment_or_spacing_findings(doc):
    for parent in ("page", "card-1"):
        assert find_misalignments(doc, parent, RADIUS, TOL) == []
    assert alignment_moves(doc, RADIUS, TOL) == []
    assert spacing_moves(doc, 4.0) == []


def test_misaligned_sibling_is_found_and_fixed_with_one_move(doc):
    move_subtree(doc, "input-2", 9, 0)
    found = find_misalignments(doc, "card-1", RADIUS, TOL)
    assert [m.component_id for m in found] == ["input-2"]
    assert found[0].target == 130 and round(found[0].residual) == 9
    moves = alignment_moves(doc, RADIUS, TOL)
    assert len(moves) == 1 and moves[0].component_id == "input-2" and moves[0].dx == -9
    assert apply_alignment(doc, RADIUS, TOL) == 1
    assert doc.require("input-2").bbox.x == 130
    assert find_misalignments(doc, "card-1", RADIUS, TOL) == []


def test_far_apart_edges_are_not_forced_together(doc):
    move_subtree(doc, "input-2", 40, 0)  # beyond the snap radius: that is a design choice
    assert find_misalignments(doc, "card-1", RADIUS, TOL) == []


def test_aligned_on_another_edge_is_not_misaligned(doc):
    # A narrower input centred under the others: left edges differ but centres agree.
    from sketchforge.design_ir import BBox
    doc.require("input-3").bbox = BBox(x=180, y=290, w=240, h=44)
    assert find_misalignments(doc, "card-1", RADIUS, TOL) == []


def test_repeated_group_and_uniform_pitch(doc):
    groups = repeated_groups(doc, "card-1")
    inputs = [g for g in groups if g.axis == "column" and len(g.member_ids) == 4]
    assert len(inputs) == 1 and inputs[0].member_ids == ("input-1", "input-2", "input-3", "input-4")
    assert inputs[0].spread(doc) == 0
    c0, pitch = robust_pitch_fit(inputs[0].centers(doc))
    assert (round(c0), round(pitch)) == (192, 60)


def test_uneven_spacing_is_repaired_by_moving_only_the_outlier(doc):
    move_subtree(doc, "input-3", 0, 11)
    moves = spacing_moves(doc, 4.0)
    assert [m.component_id for m in moves] == ["input-3"]
    assert moves[0].dy == -11
    assert apply_spacing(doc, 4.0) == 1
    assert spacing_moves(doc, 4.0) == []
    assert doc.require("input-3").bbox.y == 290


def test_containment_enforcement(doc):
    from sketchforge.design_ir import BBox
    doc.require("button-1").bbox = BBox(x=130, y=440, w=420, h=48)  # wider than the card
    report = BuildReport()
    assert enforce_containment(doc, 2.0, report) == 1
    card = doc.require("card-1").bbox
    assert doc.require("button-1").bbox.x2 <= card.x2
    assert report.clamped == ["button-1 pulled inside card-1"]
    assert validate_document(doc).warnings == []


def test_refine_document_fixes_everything_it_reports(doc):
    move_subtree(doc, "input-2", 7, 0)
    move_subtree(doc, "input-4", 0, -9)
    rep = refine_document(doc, LayoutConstraints())
    assert rep.alignment_moves >= 1 and rep.spacing_moves >= 1
    assert find_misalignments(doc, "card-1", RADIUS, TOL) == []
    assert spacing_moves(doc, 4.0) == []


def test_container_layout_inference(doc):
    spec = infer_container_layout(doc, doc.require("card-1"))
    assert spec.mode == "flex" and spec.direction == "column" and spec.inferred
    assert spec.align_items == "start" and spec.gap == 16  # 60 pitch - 44 height
    assert spec.padding == 20
    single = infer_container_layout(doc, doc.require("header-1"))
    assert single.mode == "absolute"
    assert doc.require("input-1").layout is None
    assert doc.require("card-1").type is ComponentType.CARD
