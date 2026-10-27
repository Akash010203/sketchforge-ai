"""Unit tests for screenshot discrepancy measurement and repair loop."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from sketchforge.design_ir.document import add_component, new_document
from sketchforge.design_ir.schema import BBox, Component, ComponentType, Style
from sketchforge.verification.discrepancy_repair import (
    DiscrepancyReport,
    capture_preview_screenshot,
    measure_visual_discrepancy,
    run_discrepancy_repair_loop,
)


def test_discrepancy_report_summary_and_serialization():
    report = DiscrepancyReport(
        score=0.18,
        mean_iou=0.82,
        mean_position_error_px=12.4,
        missing_components=["btn_submit"],
        mismatched_components=[{"id": "inp_email", "best_iou": 0.45}],
        repaired=True,
    )
    d = report.to_dict()
    assert d["score"] == 0.18
    assert d["mean_iou"] == 0.82
    assert d["repaired"] is True
    assert "repaired via targeted patch" in report.summary()
    assert "btn_submit" in report.summary()


def test_capture_preview_screenshot_fallback_creates_png(tmp_path):
    out = tmp_path / "preview.png"
    ok = capture_preview_screenshot("http://127.0.0.1:8000", out)
    assert ok is True
    assert out.exists()
    assert out.stat().st_size > 100


def test_measure_visual_discrepancy_with_dom_inspection(tmp_path):
    doc = new_document(name="TestDoc", width=800, height=600)
    add_component(doc, Component(
        id="c1", type=ComponentType.BUTTON, name="Submit Button",
        parent_id=doc.root_id, bbox=BBox(x=10, y=10, w=100, h=40), style=Style(), text="Submit",
    ))
    add_component(doc, Component(
        id="c2", type=ComponentType.INPUT, name="Search Input",
        parent_id=doc.root_id, bbox=BBox(x=10, y=60, w=200, h=40), style=Style(), text="Search",
    ))

    # Project with home.html containing the Submit button
    (tmp_path / "home.html").write_text("<html><body><button>Submit</button></body></html>", encoding="utf-8")

    report = measure_visual_discrepancy(None, doc, tmp_path)
    assert report.score < 1.0
    assert report.mean_iou > 0.0


def test_run_discrepancy_repair_loop_invokes_patch_when_needed(tmp_path):
    doc = new_document(name="TestDoc", width=800, height=600)
    add_component(doc, Component(
        id="c1", type=ComponentType.BUTTON, name="Button",
        parent_id=doc.root_id, bbox=BBox(x=10, y=10, w=100, h=40), style=Style(), text="Button",
    ))

    # Initial file without component
    (tmp_path / "home.html").write_text("<html><body>Empty</body></html>", encoding="utf-8")

    def mock_revise(root, instr, progress=None, **kwargs):
        # Apply patch
        (root / "home.html").write_text("<html><body><button>Button</button></body></html>", encoding="utf-8")
        return True

    with patch("sketchforge.generation.ai_generator.ai_revise_project", side_effect=mock_revise):
        emitted = []
        final_report = run_discrepancy_repair_loop(
            tmp_path,
            preview_url=None,
            design_doc=doc,
            max_attempts=1,
            threshold=0.10,
            progress=emitted.append,
        )
        assert final_report.repaired is True or final_report.score <= 0.25
