"""Image loading, normalisation, preprocessing, detection and hierarchy on generated sketches."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from sketchforge.bootstrap import VisionConfig
from sketchforge.datasets.synthetic_generator import (
    ALL_LAYOUTS,
    HELDOUT_LAYOUTS,
    TUNING_LAYOUTS,
    render_sketch,
)
from sketchforge.evaluation.benchmark_runner import run_benchmark
from sketchforge.exceptions import ImageLoadError, PreprocessingError
from sketchforge.vision.image_loader import from_array, load_image, load_image_bytes
from sketchforge.vision.normalization import flatten_illumination, normalize
from sketchforge.vision.perspective import correct_perspective
from sketchforge.vision.pipeline import analyze


def png_bytes(img: np.ndarray, ext: str = ".png") -> bytes:
    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


@pytest.fixture(scope="module")
def login_clean():
    img, truth = render_sketch(ALL_LAYOUTS["login_page"](), seed=3, condition="clean")
    return from_array(img, "login.png"), truth


# --------------------------------------------------------------------------- loading
def test_loads_png_and_jpeg_as_bgr8(tmp_path):
    img = np.full((200, 300, 3), 200, np.uint8)
    for ext in (".png", ".jpg"):
        p = tmp_path / f"a{ext}"
        p.write_bytes(png_bytes(img, ext))
        loaded = load_image(p)
        assert loaded.bgr.dtype == np.uint8 and loaded.bgr.shape == (200, 300, 3)
        assert (loaded.width, loaded.height) == (300, 200)
        assert len(loaded.sha256) == 64


def test_original_pixels_are_read_only(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(png_bytes(np.zeros((100, 100, 3), np.uint8)))
    with pytest.raises(ValueError):
        load_image(p).bgr[0, 0, 0] = 1


def test_grayscale_and_transparent_images_become_bgr():
    gray = np.full((120, 160), 90, np.uint8)
    assert load_image_bytes(png_bytes(gray), "g.png").bgr.shape == (120, 160, 3)
    rgba = np.zeros((120, 160, 4), np.uint8)  # fully transparent -> composited onto white paper
    assert load_image_bytes(png_bytes(rgba), "t.png").bgr.min() == 255


@pytest.mark.parametrize("data,name,fragment", [
    (b"", "a.png", "empty"),
    (b"not an image at all", "a.png", "not a recognised"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "a.png", "header"),
    (b"GIF89a....", "a.gif", "unsupported file type"),
])
def test_rejects_bad_files(data, name, fragment):
    with pytest.raises(ImageLoadError, match=fragment):
        load_image_bytes(data, name)


def test_rejects_wrong_size_and_missing_file(tmp_path):
    with pytest.raises(ImageLoadError, match="sides must be"):
        load_image_bytes(png_bytes(np.zeros((20, 20, 3), np.uint8)), "tiny.png")
    with pytest.raises(ImageLoadError, match="limit"):
        load_image_bytes(png_bytes(np.zeros((300, 300, 3), np.uint8)), "a.png", VisionConfig(max_file_bytes=100))
    with pytest.raises(ImageLoadError, match="no such file"):
        load_image(tmp_path / "missing.png")


def test_extension_must_match_content():
    with pytest.raises(ImageLoadError):
        load_image_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "evil.png")


# --------------------------------------------------------------------------- normalisation
def test_normalize_scales_long_side_and_reports_scale():
    img = np.full((500, 1000, 3), 240, np.uint8)
    n = normalize(img, 800)
    assert max(n.width, n.height) == 800
    assert n.scale == pytest.approx(0.8)
    assert n.original_size == (1000, 500)


def test_normalize_never_upscales_more_than_the_cap():
    n = normalize(np.full((100, 100, 3), 240, np.uint8), 1024, max_upscale=2.0)
    assert n.width == 200


def test_flatten_illumination_removes_a_shadow_but_keeps_ink():
    paper = np.tile(np.linspace(120, 250, 400, dtype=np.float32), (300, 1))  # strong left->right gradient
    paper[100:104, 50:350] = 40  # a pen stroke
    flat = flatten_illumination(paper.astype(np.uint8))
    background = np.delete(flat, np.s_[100:104], axis=0)
    assert background.std() < 12  # gradient gone
    assert flat[101, 200] < 100  # ink survives


# --------------------------------------------------------------------------- pipeline
def test_blank_page_is_a_clear_error_not_a_crash():
    with pytest.raises(PreprocessingError, match="almost no ink"):
        analyze(from_array(np.full((600, 800, 3), 245, np.uint8)))


def test_detects_login_page_structure(login_clean):
    loaded, truth = login_clean
    result = analyze(loaded)
    kinds = [d.type for d in result.detections]
    for needed in ("header", "card", "button", "input"):
        assert needed in kinds, kinds
    assert result.proposals.frame.source == "drawn_frame"
    assert 1 <= len(result.detections) < 60
    assert set(result.inference.parent) == {d.uid for d in result.detections}


def test_hierarchy_parents_contain_their_children(login_clean):
    result = analyze(login_clean[0])
    by_uid = {d.uid: d for d in result.detections}
    for uid, parent in result.inference.parent.items():
        if parent is None:
            continue
        c, p = by_uid[uid].bbox, by_uid[parent].bbox
        cx, cy = c[0] + c[2] / 2, c[1] + c[3] / 2
        assert p[0] <= cx <= p[0] + p[2] and p[1] <= cy <= p[1] + p[3]
        assert p[2] * p[3] > c[2] * c[3]  # parents are strictly larger


def test_order_lists_parents_before_children(login_clean):
    inf = analyze(login_clean[0]).inference
    position = {uid: i for i, uid in enumerate(inf.order)}
    assert len(position) == len(inf.parent)
    for uid, parent in inf.parent.items():
        if parent is not None:
            assert position[parent] < position[uid]


def test_analysis_is_deterministic(login_clean):
    a, b = analyze(login_clean[0]), analyze(login_clean[0])
    assert [(d.type, d.bbox) for d in a.detections] == [(d.type, d.bbox) for d in b.detections]


def test_every_detection_carries_evidence_and_normalised_scores(login_clean):
    for d in analyze(login_clean[0]).detections:
        assert 0.0 < d.confidence <= 1.0
        assert d.evidence
        assert d.type_scores and abs(sum(d.type_scores.values()) - 1.0) < 1e-3  # scores are rounded to 4 dp
        assert d.type in d.type_scores


def test_ambiguity_is_flagged_not_hidden():
    """A rectangle with no label can be a button or an input; the detector must say so."""
    result = analyze(from_array(render_sketch(ALL_LAYOUTS["login_page"](), seed=5, condition="clean")[0]))
    controls = [d for d in result.detections if d.type in ("button", "input")]
    assert controls
    assert all(("button" in d.type_scores and "input" in d.type_scores) for d in controls)


def test_boxes_map_back_to_source_pixels():
    img, truth = render_sketch(ALL_LAYOUTS["login_page"](), seed=3, condition="clean")
    big = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    result = analyze(from_array(big))
    xs = [result.source_box(d.bbox) for d in result.detections]
    assert max(b[0] + b[2] for b in xs) <= big.shape[1] + 2
    assert max(b[1] + b[3] for b in xs) <= big.shape[0] + 2


def test_phone_and_desktop_sketches_get_different_design_widths():
    phone = analyze(from_array(render_sketch(ALL_LAYOUTS["mobile_form"](), seed=3, condition="clean")[0]))
    desk = analyze(from_array(render_sketch(ALL_LAYOUTS["dashboard"](), seed=3, condition="clean")[0]))
    cfg = VisionConfig()
    assert phone.proposals.frame.bbox[2] * phone.design_scale == pytest.approx(cfg.design_width_portrait, rel=0.01)
    assert desk.proposals.frame.bbox[2] * desk.design_scale == pytest.approx(cfg.design_width_landscape, rel=0.01)


def test_perspective_corrects_a_tilted_page_and_maps_boxes_to_source():
    img = np.full((700, 900, 3), 235, np.uint8)
    quad = np.array([[160, 90], [730, 150], [680, 610], [115, 550]], np.int32)
    cv2.fillConvexPoly(img, quad, (255, 255, 255))
    cv2.polylines(img, [quad], True, (20, 20, 20), 5)
    cv2.rectangle(img, (270, 260), (600, 280), (20, 20, 20), 4)

    corrected = correct_perspective(img)
    assert corrected.corrected
    assert corrected.matrix is not None
    assert corrected.bgr.shape[1] != img.shape[1]
    mapped = cv2.perspectiveTransform(
        np.array([[[0.0, 0.0]]], np.float32), np.linalg.inv(corrected.matrix)
    )[0, 0]
    assert np.linalg.norm(mapped - corrected.quad_pts[0]) < 2


def test_perspective_leaves_a_blank_image_unchanged():
    img = np.full((300, 400, 3), 245, np.uint8)
    result = correct_perspective(img)
    assert not result.corrected
    assert result.matrix is None
    assert result.bgr is img


def test_perspective_skips_axis_aligned_border_near_canvas_edges():
    img = np.full((300, 400, 3), 245, np.uint8)
    cv2.rectangle(img, (8, 8), (391, 291), (20, 20, 20), 4)
    result = correct_perspective(img)
    assert not result.corrected
    assert result.bgr is img
    assert any("axis-aligned page border" in note for note in result.notes)


# --------------------------------------------------------------------------- regression floors
@pytest.mark.slow
def test_detection_benchmark_does_not_regress():
    """Floors sit a little below the measured values (docs/EXPERIMENT_LOG.md), so a real regression
    fails while normal noise does not. Synthetic sketches only."""
    tuning = run_benchmark(TUNING_LAYOUTS, ["clean", "shadow", "noisy"], [21, 22]).aggregate()["all"]
    heldout = run_benchmark(HELDOUT_LAYOUTS, ["clean", "shadow", "noisy"], [21, 22]).aggregate()["all"]
    assert tuning["failures"] == 0 and heldout["failures"] == 0
    assert tuning["f1"] >= 0.95 and tuning["type_accuracy"] >= 0.95
    assert heldout["f1"] >= 0.95 and heldout["type_accuracy"] >= 0.88
    assert min(tuning["mean_iou"], heldout["mean_iou"]) >= 0.78
