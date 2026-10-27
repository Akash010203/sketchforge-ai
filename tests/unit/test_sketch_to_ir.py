"""Vision result -> Design IR, on generated sketches (synthetic: see docs/KNOWN_LIMITATIONS.md)."""

import pytest

from sketchforge.datasets.synthetic_generator import ALL_LAYOUTS, render_sketch
from sketchforge.design_ir import (
    ComponentType,
    document_hash,
    from_json,
    to_json,
    validate_document,
)
from sketchforge.layout.design_refinement import build_document
from sketchforge.vision.image_loader import from_array
from sketchforge.vision.pipeline import analyze


@pytest.fixture(scope="module")
def login():
    img, gt = render_sketch(ALL_LAYOUTS["login_page"](), seed=11, condition="clean")
    result = analyze(from_array(img, name="login.png"))
    doc, report = build_document(result)
    return img, gt, result, doc, report


def test_document_is_valid_and_round_trips(login):
    _, _, _, doc, _ = login
    report = validate_document(doc)
    assert report.ok and report.warnings == []
    assert from_json(to_json(doc)) == doc


def test_expected_structure_for_the_login_sketch(login):
    _, _, _, doc, _ = login
    types = [c.type for c in doc.components]
    count = lambda t: types.count(t)  # noqa: E731
    assert count(ComponentType.HEADER) == 1 and count(ComponentType.CARD) == 1
    assert count(ComponentType.INPUT) == 2 and count(ComponentType.BUTTON) == 1
    assert count(ComponentType.CHECKBOX) == 1 and count(ComponentType.DIVIDER) == 1
    card = next(c for c in doc.components if c.type is ComponentType.CARD)
    inside = {doc.require(i).type for i in doc.children_ids(card.id)}
    assert {ComponentType.INPUT, ComponentType.BUTTON, ComponentType.CHECKBOX} <= inside
    header = next(c for c in doc.components if c.type is ComponentType.HEADER)
    assert doc.children_ids(header.id), "header should contain the logo and navigation"


def test_text_is_placeholder_and_flagged(login):
    _, _, _, doc, _ = login
    for c in doc.components:
        if c.type in (ComponentType.TEXT, ComponentType.HEADING, ComponentType.BUTTON, ComponentType.INPUT):
            assert c.text and c.text_is_inferred, f"{c.id} must be flagged as inferred text"
        else:
            assert c.text is None and not c.text_is_inferred


def test_recognized_handwriting_is_user_text(monkeypatch):
    from sketchforge.vision import pipeline

    monkeypatch.setenv("SKETCHFORGE_OCR_MODEL", "test-model")
    monkeypatch.setattr(pipeline, "recognize_regions", lambda gray, regions: ["Welcome"] * len(regions))
    img, _ = render_sketch(ALL_LAYOUTS["login_page"](), seed=11, condition="clean")
    doc, _ = build_document(analyze(from_array(img, name="login.png")))
    recognized = [c for c in doc.components if c.text == "Welcome"]
    assert recognized and all(not c.text_is_inferred for c in recognized)


def test_provenance_is_recorded(login):
    img, _, result, doc, _ = login
    meta = doc.metadata
    assert meta.source_image_sha256 == result.loaded.sha256
    assert meta.source_size == (img.shape[1], img.shape[0])
    assert meta.source_transform is not None
    for c in doc.components:
        if c.id == doc.root_id:
            continue
        assert c.detection is not None and c.detection.source == "heuristic"
        assert c.detection.source_bbox is not None and c.detection.evidence
        assert 0.0 <= c.detection.confidence <= 1.0
        assert sum(c.detection.type_scores.values()) == pytest.approx(1.0, abs=0.01)


def test_source_transform_maps_design_back_onto_the_sketch(login):
    """Design boxes must land within a few design px of where the sketch had them."""
    _, _, _, doc, _ = login
    t = doc.metadata.source_transform
    worst = 0.0
    for c in doc.components:
        if c.id == doc.root_id or c.type is ComponentType.DIVIDER:
            continue
        s = c.detection.source_bbox
        ex, ey = (s.x - t.offset_x) * t.scale, (s.y - t.offset_y) * t.scale
        worst = max(worst, abs(c.bbox.x - ex), abs(c.bbox.y - ey))
    assert worst < 18.0, f"largest drift {worst:.1f}px exceeds snapping radius + text growth"


def test_page_matches_the_drawn_frame(login):
    _, gt, _, doc, _ = login
    assert doc.page.width == pytest.approx(1024, abs=1)
    gt_page = next(c for c in gt["components"] if c["type"] == "page")["bbox"]
    assert doc.page.height / doc.page.width == pytest.approx(gt_page[3] / gt_page[2], rel=0.02)


def test_construction_is_deterministic(login):
    img, _, _, doc, _ = login
    doc2, _ = build_document(analyze(from_array(img, name="login.png")))
    assert document_hash(doc2) == document_hash(doc)


def test_unrefined_build_keeps_raw_geometry(login):
    img, *_ = login
    raw, report = build_document(analyze(from_array(img, name="login.png")), refine=False)
    assert report.alignment_moves == 0 and report.spacing_moves == 0
    assert validate_document(raw).errors == []


@pytest.mark.parametrize("layout", sorted(ALL_LAYOUTS))
def test_every_layout_builds_a_valid_document(layout):
    img, _ = render_sketch(ALL_LAYOUTS[layout](), seed=12, condition="shadow")
    doc, _ = build_document(analyze(from_array(img)))
    report = validate_document(doc)
    assert report.ok and not report.warnings, report.to_dict()
    assert len(doc.components) >= 8
