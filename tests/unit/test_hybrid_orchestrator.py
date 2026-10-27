"""Unit tests for HybridOrchestrator and formal state machine."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from sketchforge.orchestration.hybrid_orchestrator import (
    HybridJobState,
    HybridOrchestrator,
    get_hybrid_orchestrator,
)


def test_orchestrator_job_lifecycle_transitions():
    orch = HybridOrchestrator()
    job = orch.create_job("Build a habit tracker")
    assert job.state == HybridJobState.QUEUED
    assert job.status == "running"

    job.transition(HybridJobState.PLANNING_SPEC, "Requesting AppSpec plan…")
    assert job.state == HybridJobState.PLANNING_SPEC
    assert len(job.history) == 1

    job.transition(HybridJobState.GENERATING_FILES, "Generating 12 project files…")
    assert job.state == HybridJobState.GENERATING_FILES
    assert len(job.history) == 2

    job.transition(HybridJobState.COMPLETED, "Project generation finished.")
    assert job.state == HybridJobState.COMPLETED
    assert job.status == "complete"

    d = job.to_dict()
    assert d["status"] == "complete"
    assert d["state"] == "completed"
    assert len(d["history"]) == 3


def test_orchestrator_cancellation():
    orch = HybridOrchestrator()
    job = orch.create_job("Build a note app")
    assert not job.is_cancelled

    cancelled = orch.cancel_job(job.id)
    assert cancelled is True
    assert job.is_cancelled
    assert job.state == HybridJobState.CANCELLED
    assert job.status == "cancelled"


def test_orchestrator_singleton():
    o1 = get_hybrid_orchestrator()
    o2 = get_hybrid_orchestrator()
    assert o1 is o2


def test_orchestrator_run_pipeline_success(tmp_path):
    orch = HybridOrchestrator()
    job = orch.create_job("Build an expense manager")

    # Mock ai_generate_project to create a directory
    proj_dir = tmp_path / "expense-manager"
    proj_dir.mkdir()
    (proj_dir / "home.html").write_text("<h1>Expense</h1>", encoding="utf-8")

    with patch("sketchforge.generation.ai_generator.ai_generate_project", return_value=proj_dir):
        completed_job = orch.run_pipeline(job.id, tmp_path)
        assert completed_job.state == HybridJobState.COMPLETED
        assert completed_job.project_slug == "expense-manager"


def test_orchestrator_refuses_sketch_backed_generation_after_analysis_failure(tmp_path):
    orch = HybridOrchestrator()
    job = orch.create_job("Build a sketch-backed app", sketch_data=b"not an image")

    result = orch.run_pipeline(job.id, tmp_path)

    assert result.state == HybridJobState.FAILED
    assert result.status == "failed"
    assert result.error and "Sketch analysis failed" in result.error


def test_orchestrator_template_fallback_is_labeled(tmp_path):
    orch = HybridOrchestrator()
    job = orch.create_job("Build a note app")

    with patch("sketchforge.generation.ai_generator.ai_generate_project", return_value=None):
        result = orch.run_pipeline(job.id, tmp_path)

    assert result.state == HybridJobState.COMPLETED
    meta = (result.project_root / ".sketchforge_meta.json").read_text(encoding="utf-8")
    assert '"generation": "template_fallback"' in meta
