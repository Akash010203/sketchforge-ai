import numpy as np
import pytest

from sketchforge.design_ir import BBox, LayoutConstraints, move_subtree
from sketchforge.domain.color_system import (
    best_text_color,
    contrast_ratio,
    effective_background,
    hex_to_rgba,
)
from sketchforge.domain.typography import estimate_text_width, placeholder_for
from sketchforge.editor import SetStyleCommand, SetTextCommand, SetTypographyCommand, UndoStack
from sketchforge.evaluation import evaluate_document
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.image_metrics import changed_bbox, changed_pixel_ratio, ssim
from sketchforge.rendering.render_snapshot import render_image
from support import make_form_document

C = LayoutConstraints()


@pytest.fixture
def doc():
    return make_form_document()


def codes(result):
    return sorted({i.code for i in result.issues})


def test_clean_document_has_no_issues(doc):
    result = evaluate_document(doc, C)
    assert result.issues == [], [i.message for i in result.issues]
    assert result.metrics["issues_total"] == 0
    assert result.fidelity is None and "fidelity" in result.notes[0]


def test_containment_overflow_is_measured(doc):
    doc.require("button-1").bbox = BBox(x=130, y=440, w=340, h=48)
    move_subtree(doc, "button-1", 60, 0)  # right edge 530 vs card edge 500
    result = evaluate_document(doc, C)
    (issue,) = result.by_code(I.OVERFLOW_PARENT)
    assert issue.component_ids == ("button-1",) and issue.discriminator == "right"
    assert issue.measure == pytest.approx(30.0)
    assert result.magnitude(I.OVERFLOW_PARENT) == pytest.approx(30.0)


def test_page_overflow(doc):
    move_subtree(doc, "header-1", 0, -10)
    result = evaluate_document(doc, C)
    assert any(i.code == I.OVERFLOW_PAGE and i.measure == pytest.approx(10.0) for i in result.issues)


def test_misalignment_and_spacing_issues_have_stable_keys(doc):
    move_subtree(doc, "input-2", 8, 0)
    move_subtree(doc, "input-4", 0, 12)
    result = evaluate_document(doc, C)
    assert {I.MISALIGNED, I.UNEVEN_SPACING} <= set(codes(result))
    mis = result.by_code(I.MISALIGNED)[0]
    assert mis.key == "MISALIGNED:input-2:left" and mis.measure == pytest.approx(8.0)
    again = evaluate_document(doc, C)
    assert again.keys() == result.keys()


def test_overlap_between_siblings(doc):
    move_subtree(doc, "input-2", 0, -30)  # now overlaps input-1
    result = evaluate_document(doc, C)
    overlap = result.by_code(I.OVERLAP)
    assert overlap and overlap[0].component_ids == ("input-1", "input-2")
    assert 0.2 < overlap[0].measure < 0.5


def test_text_overflow_and_clipping(doc):
    stack = UndoStack(doc)
    stack.execute(SetTextCommand("button-1", "A very long call to action that cannot fit inside"))
    stack.execute(SetTypographyCommand("heading-1", font_size=60))
    result = evaluate_document(doc, C)
    assert I.TEXT_OVERFLOW in codes(result) and I.TEXT_CLIPPED in codes(result)
    ov = result.by_code(I.TEXT_OVERFLOW)[0]
    assert ov.measure == pytest.approx(
        estimate_text_width("A very long call to action that cannot fit inside", 16, 600) - (340 - 16), abs=0.5)


def test_contrast_uses_the_effective_background(doc):
    stack = UndoStack(doc)
    stack.execute(SetStyleCommand("button-1", fill="#ffffff"))  # white label on white
    result = evaluate_document(doc, C)
    (issue,) = result.by_code(I.LOW_CONTRAST)
    assert issue.component_ids == ("button-1",) and issue.details["ratio"] == pytest.approx(1.0, abs=0.01)
    # a transparent fill defers to the ancestor behind it
    stack.execute(SetStyleCommand("button-1", fill="transparent"))
    bg = effective_background(doc, doc.require("button-1"))
    assert bg == (255.0, 255.0, 255.0)  # the card is white


def test_small_controls_and_fonts(doc):
    doc.require("input-1").bbox = BBox(x=130, y=170, w=340, h=18)
    UndoStack(doc).execute(SetTypographyCommand("input-2", font_size=8))
    result = evaluate_document(doc, C)
    assert {I.TOUCH_TARGET_SMALL, I.FONT_TOO_SMALL} <= set(codes(result))


def test_issue_severity_counts(doc):
    move_subtree(doc, "button-1", 60, 0)
    result = evaluate_document(doc, C)
    assert result.metrics["issues_error"] >= 1
    assert result.metrics["count.OVERFLOW_PARENT"] == 1


def test_wcag_contrast_reference_values():
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert contrast_ratio((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.02)  # #777 on white
    assert contrast_ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
    assert hex_to_rgba("#11223380") == (17, 34, 51, pytest.approx(128 / 255))


def test_best_text_color_makes_minimal_change():
    white = (255.0, 255.0, 255.0)
    assert best_text_color(white, "#0f172a") == "#0f172a"  # already fine: unchanged
    fixed = best_text_color(white, "#aaaaaa")
    assert contrast_ratio(tuple(float(int(fixed[i:i + 2], 16)) for i in (1, 3, 5)), white) >= 4.5
    assert fixed.startswith("#") and fixed != "#0f172a"  # darkened gray, not forced to slate
    assert best_text_color((37, 99, 235), "#222222") == "#ffffff"  # dark text on blue -> white


def test_image_metrics_detect_and_localise_a_change(doc):
    a = render_image(doc)
    assert ssim(a, a) == pytest.approx(1.0) and changed_pixel_ratio(a, a) == 0 and changed_bbox(a, a) is None
    UndoStack(doc).execute(SetStyleCommand("button-1", fill="#16a34a"))
    b = render_image(doc)
    assert ssim(a, b) < 1.0
    ratio = changed_pixel_ratio(a, b)
    assert 0.0 < ratio < 0.1
    x, y, w, h = changed_bbox(a, b)
    assert 125 <= x <= 135 and 435 <= y <= 445 and 335 <= w <= 345 and 43 <= h <= 53
    with pytest.raises(ValueError):
        ssim(a, a[:10])


def test_placeholder_text_fits_its_box():
    for kind, w, fs, weight in [("text", 300, 16, 400), ("heading", 200, 28, 700),
                                ("button", 120, 16, 600), ("input", 260, 16, 400), ("text", 40, 12, 400)]:
        assert estimate_text_width(placeholder_for(kind, w, fs, weight), fs, weight) <= w
    assert np.isfinite(estimate_text_width("", 16))
