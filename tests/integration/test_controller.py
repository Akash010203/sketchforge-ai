"""The application controller driven without any UI: import, edit, undo, evaluate, repair, save."""

from __future__ import annotations

import pytest

from sketchforge.application.app_controller import AppController, NoProjectError
from sketchforge.application.task_manager import TaskManager
from sketchforge.design_ir.serialization import document_hash
from sketchforge.exceptions import EditError, SketchForgeError
from sketchforge.utilities.paths import repo_root

SAMPLE = repo_root() / "assets" / "sample_sketches" / "login_page_synthetic.png"


@pytest.fixture(scope="module")
def imported():
    ctl = AppController(tasks=TaskManager(max_workers=1))
    ctl.import_sketch(SAMPLE)
    yield ctl
    ctl.close()


@pytest.fixture
def ctl(imported):
    """A fresh controller sharing the (expensive) import result: reopen from a snapshot."""
    c = AppController(tasks=TaskManager(max_workers=1))
    c.import_sketch(SAMPLE)
    yield c
    c.close()


def test_no_project_until_import():
    c = AppController(tasks=TaskManager(max_workers=1))
    with pytest.raises(NoProjectError):
        _ = c.document
    c.close()


def test_import_produces_valid_measured_document(imported):
    assert imported.has_project
    assert len(imported.document.components) > 5
    assert imported.project.evaluation is not None
    assert imported.project.source is not None
    assert not imported.project.dirty


def test_import_failure_is_reported_not_swallowed(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    c = AppController(tasks=TaskManager(max_workers=1))
    errors: list[str] = []
    c.events.subscribe("error", lambda message: errors.append(message))
    with pytest.raises(SketchForgeError):
        c.import_sketch(bad)
    assert errors and "load_image" in errors[0]
    assert not c.has_project
    c.close()


def test_edit_text_color_position_size_then_undo_all(ctl):
    doc = ctl.document
    button = next(c for c in doc.components if c.type.value == "button")
    start = document_hash(doc)
    ctl.edit_property(button.id, "text", "Sign in")
    ctl.edit_property(button.id, "fill", "#16a34a")
    ctl.move_component(button.id, 5, 0)
    ctl.resize_component(button.id, button.bbox.w + 10, button.bbox.h)
    assert doc.require(button.id).text == "Sign in"
    assert doc.require(button.id).style.fill == "#16a34a"
    assert ctl.project.dirty
    assert document_hash(doc) != start
    while ctl.undo():
        pass
    assert document_hash(ctl.document) == start  # exact, not approximate
    assert ctl.redo() is not None


def test_invalid_edit_leaves_document_untouched(ctl):
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    before = document_hash(ctl.document)
    with pytest.raises(EditError):
        ctl.edit_property(comp.id, "fill", "not-a-color")
    assert document_hash(ctl.document) == before
    assert not ctl.project.stack.can_undo


def test_render_is_cached_per_revision_and_refreshed_after_edit(ctl):
    first = ctl.render()
    assert ctl.render() is first
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    ctl.edit_property(comp.id, "text", "Go")
    second = ctl.render()
    assert second is not first
    assert "Go" in second.html


def test_selection_by_point_and_pruned_on_delete(ctl):
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    hit = ctl.select_at(comp.bbox.cx, comp.bbox.cy)
    assert hit is not None and hit.id == comp.id
    assert ctl.project.selection.primary == comp.id


def test_inject_then_repair_improves_and_is_one_undo_step(ctl):
    start = document_hash(ctl.document)
    injection = ctl.inject_error("overflow")
    assert ctl.project.evaluation is not None
    assert any(i.code == injection.expected_code for i in ctl.project.evaluation.issues)
    broken = document_hash(ctl.document)
    assert broken != start

    report = ctl.run_repair(injection=injection)
    assert report.outcome.value == "IMPROVED"
    assert not report.final.issues
    assert document_hash(ctl.document) == report.hash_after
    assert ctl.project.last_report is report

    ctl.undo()  # the whole repair is one step
    assert document_hash(ctl.document) == broken


def test_repair_on_clean_document_changes_nothing(ctl):
    before = document_hash(ctl.document)
    report = ctl.run_repair()
    assert document_hash(ctl.document) == before
    assert not report.accepted


def test_async_repair_applies_result(ctl):
    ctl.inject_error("misalignment")
    done = ctl.run_repair_async()
    ctl.tasks.wait(done, timeout=60)
    assert done.error is None
    assert done.result.outcome.value in ("IMPROVED", "NO_MEASURABLE_DIFFERENCE")
    assert document_hash(ctl.document) == done.result.hash_after


def test_repair_refuses_to_apply_over_a_concurrent_edit(ctl):
    ctl.inject_error("overflow")
    from sketchforge.design_ir.serialization import from_dict
    from sketchforge.orchestration.repair_workflow import run_repair

    copy = from_dict(ctl.document.snapshot())
    revision = ctl.project.stack.revision
    report = run_repair(copy, constraints=ctl.config.constraints, policy=ctl.config.regression)
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    ctl.edit_property(comp.id, "text", "edited meanwhile")
    with pytest.raises(EditError):
        ctl._apply_repair(report, copy, revision)
    assert next(c for c in ctl.document.components if c.id == comp.id).text == "edited meanwhile"


def test_save_and_reopen_round_trip(ctl, tmp_path):
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    ctl.edit_property(comp.id, "text", "Persist me")
    root = ctl.save_project(tmp_path / "proj")
    assert not ctl.project.dirty
    other = AppController(tasks=TaskManager(max_workers=1))
    other.open_project(root)
    assert document_hash(other.document) == document_hash(ctl.document)
    assert other.project.source is not None
    other.close()


def test_events_fire(ctl):
    seen: list[str] = []
    for name in ("document_changed", "evaluation_changed", "selection_changed", "repair_finished"):
        ctl.events.subscribe(name, lambda _n=name, **kw: seen.append(_n))
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    ctl.edit_property(comp.id, "text", "x")
    ctl.select([comp.id])
    ctl.evaluate()
    assert {"document_changed", "selection_changed", "evaluation_changed"} <= set(seen)


def test_export_writes_all_formats(ctl, tmp_path):
    paths = ctl.export(tmp_path)
    for kind in ("svg", "html", "css", "png", "json"):
        assert paths[kind].is_file() and paths[kind].stat().st_size > 0
