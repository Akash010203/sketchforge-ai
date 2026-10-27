"""Drive the real PySide6 window headlessly (Qt 'offscreen' platform) like a user would."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sketchforge.application.app_controller import AppController  # noqa: E402
from sketchforge.application.task_manager import TaskManager  # noqa: E402
from sketchforge.design_ir.serialization import document_hash  # noqa: E402
from sketchforge.ui.main_window import MainWindow  # noqa: E402
from sketchforge.utilities.paths import repo_root  # noqa: E402

SAMPLE = repo_root() / "assets" / "sample_sketches" / "login_page_synthetic.png"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, predicate=lambda: False, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def window(app):
    controller = AppController(tasks=TaskManager(max_workers=2))
    win = MainWindow(controller)
    win.show()
    win.confirm_discard = lambda: True
    yield win
    win.close()


@pytest.fixture
def loaded(window, app):
    window.import_path(SAMPLE)  # asynchronous, like the real menu action
    assert pump(app, lambda: window.act_repair.isEnabled() and not window.progress.busy)
    pump(app, lambda: False, 0.2)
    return window


def test_starts_empty_and_import_is_asynchronous(window, app):
    assert not window.controller.has_project
    assert not window.act_undo.isEnabled() and not window.act_repair.isEnabled()
    window.import_path(SAMPLE)
    assert window.progress.busy  # the UI thread returned before the import finished
    # Wait for the *UI* to reflect the project: the controller flips has_project on the worker
    # thread before the queued signal reaches the GUI thread, so has_project alone is racy.
    assert pump(app, lambda: window.act_repair.isEnabled())
    assert window.controller.has_project and not window.progress.busy


def test_import_populates_every_view(loaded):
    ctl = loaded.controller
    n = len(ctl.document.components)
    assert loaded.tree.topLevelItemCount() == 1
    assert len(loaded.tree._items) == n
    assert loaded.canvas._svg_item is not None
    assert "<html" in loaded.preview.html_view.toPlainText().lower() or "<div" in loaded.preview.html_view.toPlainText()
    assert '"components"' in loaded.preview.json_view.toPlainText()
    assert loaded.sketch_view.image_label.pixmap() is not None and not loaded.sketch_view.image_label.pixmap().isNull()


def test_tree_selection_drives_properties_and_canvas(loaded, app):
    button = next(c for c in loaded.controller.document.components if c.type.value == "button")
    loaded.tree._items[button.id].setSelected(True)
    app.processEvents()
    assert loaded.controller.project.selection.primary == button.id
    assert loaded.properties.id_label.text().startswith(button.id)
    assert loaded.properties.x_spin.value() == pytest.approx(button.bbox.x, abs=0.06)
    assert any(item.rect().width() == pytest.approx(button.bbox.w) for item in loaded.canvas._overlays)


def test_property_edits_text_colour_position_size(loaded, app):
    ctl = loaded.controller
    button = next(c for c in ctl.document.components if c.type.value == "button")
    ctl.select([button.id])
    app.processEvents()
    p = loaded.properties
    start = document_hash(ctl.document)
    orig = button.bbox  # BBox is immutable; `button` itself is the live component and will change

    p.text_edit.setText("Sign in")
    p.text_edit.editingFinished.emit()
    p.fill_btn.color_chosen.emit("#16a34a")
    p.x_spin.setValue(orig.x + 12)
    p.w_spin.setValue(orig.w + 20)
    app.processEvents()

    now = ctl.document.require(button.id)
    assert now.text == "Sign in" and not now.text_is_inferred
    assert now.style.fill == "#16a34a"
    assert now.bbox.x == pytest.approx(orig.x + 12, abs=0.06)
    assert now.bbox.w == pytest.approx(orig.w + 20, abs=0.06)
    assert "Sign in" in loaded.preview.html_view.toPlainText()
    for _ in range(4):
        loaded.undo()
    assert document_hash(ctl.document) == start


def test_natural_language_prompt_enter_applies_edit_and_refreshes_views(loaded, app):
    ctl = loaded.controller
    button = next(c for c in ctl.document.components if c.type.value == "button")
    requested_color, expected_fill = (("purple", "#7c3aed")
                                      if button.style.fill != "#7c3aed" else ("orange", "#ea580c"))
    old_svg = ctl.render().svg
    old_renderer = loaded.canvas._renderer
    revision = ctl.project.stack.revision

    loaded.edit_prompt.setFocus()
    QTest.keyClicks(loaded.edit_prompt, f"make {button.id} {requested_color}")
    QTest.keyClick(loaded.edit_prompt, Qt.Key.Key_Return)
    app.processEvents()

    assert ctl.document.require(button.id).style.fill == expected_fill
    assert ctl.project.stack.revision == revision + 1
    assert ctl.render().svg != old_svg
    assert loaded.canvas._renderer is not old_renderer and loaded.canvas._renderer.isValid()
    assert loaded.edit_prompt.text() == ""
    assert loaded.act_undo.isEnabled()

    loaded.undo()
    assert ctl.document.require(button.id).style.fill != expected_fill


def test_rejected_edit_reports_and_snaps_back(loaded, app):
    ctl = loaded.controller
    comp = next(c for c in ctl.document.components if c.type.value == "button")
    ctl.edit_property(comp.id, "text", "x")
    ctl.select([comp.id])
    ctl.document.require(comp.id).locked = True
    loaded.properties.refresh()
    before = document_hash(ctl.document)
    loaded.properties.x_spin.setEnabled(True)
    loaded.properties.x_spin.setValue(comp.bbox.x + 30)
    app.processEvents()
    assert document_hash(ctl.document) == before
    assert loaded.properties.x_spin.value() == pytest.approx(comp.bbox.x, abs=0.06)
    assert loaded.statusBar().currentMessage()


def test_canvas_click_selects_and_drag_moves_in_one_undo_step(loaded, app):
    ctl = loaded.controller
    canvas = loaded.canvas
    button = next(c for c in ctl.document.components if c.type.value == "button")
    scene_pt = button.bbox
    start = canvas.mapFromScene(scene_pt.cx, scene_pt.cy)
    vp = canvas.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=start)
    app.processEvents()
    assert ctl.project.selection.primary == button.id

    revision = ctl.project.stack.revision
    orig = button.bbox
    end = QPoint(start.x() + 30, start.y() + 18)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 7):
        QTest.mouseMove(vp, QPoint(start.x() + 5 * step, start.y() + 3 * step))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    moved = ctl.document.require(button.id)
    assert moved.bbox.x > orig.x and moved.bbox.y > orig.y
    assert ctl.project.stack.revision == revision + 1  # the whole drag is one command


def test_inject_then_auto_repair_from_the_panel(loaded, app):
    ctl = loaded.controller
    start = document_hash(ctl.document)
    panel = loaded.correction
    panel.kind_box.setCurrentText("overflow")
    panel.inject_btn.click()
    app.processEvents()
    assert ctl.project.evaluation.issues
    assert panel.table.rowCount() >= 1
    assert any("OVERFLOW" in panel.table.item(r, 1).text() for r in range(panel.table.rowCount()))

    panel.repair_btn.click()
    assert pump(app, lambda: ctl.project.last_report is not None and panel.repair_btn.isEnabled())
    pump(app, lambda: False, 0.2)
    report = ctl.project.last_report
    assert report.outcome.value == "IMPROVED" and not report.final.issues
    assert panel.table.rowCount() == 0
    assert "IMPROVED" in panel.report_view.toPlainText()
    assert document_hash(ctl.document) == report.hash_after
    # one undo reverts the repair, one more reverts the injection
    loaded.undo()
    loaded.undo()
    assert document_hash(ctl.document) == start


def test_save_export_and_screenshot(loaded, app, tmp_path):
    loaded.controller.inject_error("overflow")
    app.processEvents()
    pix = loaded.grab()
    assert not pix.isNull() and pix.width() > 800
    assert pix.save(str(tmp_path / "window.png"))
    image = pix.toImage()
    colours = {image.pixel(x, y) for x in range(0, image.width(), 37) for y in range(0, image.height(), 41)}
    assert len(colours) > 8  # not a blank window
    loaded.controller.save_project(tmp_path / "proj")
    assert (tmp_path / "proj" / "design.json").is_file()
