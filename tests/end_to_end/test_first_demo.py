"""Milestone 1 acceptance: the documented demo command works and its artifacts are consistent."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from sketchforge.__main__ import main
from sketchforge.design_ir.serialization import document_hash, load_document
from sketchforge.utilities.paths import repo_root


@pytest.fixture(scope="module")
def demo_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    assert main(["demo", "--out", str(out)]) == 0
    return out


def test_demo_writes_expected_artifacts(demo_out):
    for rel in (
        "design_initial.json", "design_before_repair.json", "design_final.json", "summary.json",
        "renders/before_repair.svg", "renders/before_repair.html", "renders/after_repair.png",
        "reports/repair_report.json", "reports/repair_report.md", "reports/repair_report_comparison.png",
        "diagnostics/detections.png",
    ):
        assert (demo_out / rel).is_file(), rel


def test_demo_measured_a_known_fault_and_fixed_it(demo_out):
    report = json.loads((demo_out / "reports" / "repair_report.json").read_text())
    assert report["outcome"] == "IMPROVED"
    assert report["injection"]["kind"] == "overflow"
    assert report["initial"]["metrics"]["issues_error"] >= 1
    assert report["final"]["metrics"]["issues_total"] == 0
    assert any(r["decision"] == "accepted" for r in report["attempts"])


def test_demo_final_design_matches_report_hash_and_is_valid(demo_out):
    summary = json.loads((demo_out / "summary.json").read_text())
    final = load_document(demo_out / "design_final.json")
    assert summary["document"]["hash"] == document_hash(final)
    assert summary["network"].startswith("none")
    before = load_document(demo_out / "design_before_repair.json")
    assert document_hash(before) != document_hash(final)


def test_demo_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert main(["demo", "--out", str(a)]) == 0
    assert main(["demo", "--out", str(b)]) == 0
    assert (a / "design_final.json").read_text() == (b / "design_final.json").read_text()
    assert (a / "design_initial.json").read_text() == (b / "design_initial.json").read_text()


def test_demo_without_repair_reports_the_fault_only(tmp_path):
    code = main(["demo", "--out", str(tmp_path), "--no-repair"])
    assert code == 0
    assert not (tmp_path / "reports" / "repair_report.json").exists()


def test_demo_rejects_a_missing_image(tmp_path):
    assert main(["demo", "--image", str(tmp_path / "nope.png"), "--out", str(tmp_path)]) == 2


def test_module_entry_point_runs_as_a_subprocess(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-I", "-m", "sketchforge", "demo", "--out", str(tmp_path)],
        capture_output=True, text=True, cwd=repo_root(), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "IMPROVED" in proc.stdout
