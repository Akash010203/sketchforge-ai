import xml.etree.ElementTree as ET

import numpy as np
import pytest

from sketchforge.design_ir import document_hash
from sketchforge.editor import MoveCommand, SetTextCommand, SetVisibleCommand, UndoStack
from sketchforge.rendering.css_renderer import render_css
from sketchforge.rendering.html_renderer import render_html
from sketchforge.rendering.render_snapshot import render_image, render_png_bytes
from sketchforge.rendering.renderer import render_all
from sketchforge.rendering.svg_renderer import render_svg
from support import make_form_document

NS = {"svg": "http://www.w3.org/2000/svg"}


@pytest.fixture
def doc():
    return make_form_document()


def _groups(svg):
    root = ET.fromstring(svg)
    return {g.get("data-sf-id"): g for g in root.iter("{http://www.w3.org/2000/svg}g")}


def test_svg_is_well_formed_and_has_one_group_per_component(doc):
    svg = render_svg(doc)
    root = ET.fromstring(svg)
    assert root.get("viewBox") == "0 0 600 600"
    groups = _groups(svg)
    assert set(groups) == {c.id for c in doc.components}
    assert groups["button-1"].get("data-sf-type") == "button"


def test_rendering_is_deterministic_and_tracks_edits(doc):
    a, b = render_svg(doc), render_svg(doc)
    assert a == b
    h = document_hash(doc)
    stack = UndoStack(doc)
    stack.execute(SetTextCommand("heading-1", "Changed"))
    assert "Changed" in render_svg(doc) and "Changed" not in a
    stack.undo()
    assert document_hash(doc) == h and render_svg(doc) == a


def test_text_is_escaped(doc):
    UndoStack(doc).execute(SetTextCommand("heading-1", "<b>&\"x\"</b>"))
    svg = render_svg(doc)
    ET.fromstring(svg)  # still well-formed
    assert "<b>" not in svg
    html = render_html(doc)
    assert "<b>" not in html and "&lt;b&gt;" in html


def test_hidden_components_and_their_children_are_not_drawn(doc):
    UndoStack(doc).execute(SetVisibleCommand("card-1", False))
    groups = _groups(render_svg(doc))
    assert "card-1" not in groups and "input-1" not in groups and "header-1" in groups
    assert 'data-sf-id="input-1"' not in render_html(doc)


def test_stroke_is_inset_so_outline_matches_bbox(doc):
    groups = _groups(render_svg(doc))
    rect = groups["input-1"].find("svg:rect", NS)
    x, w, sw = float(rect.get("x")), float(rect.get("width")), float(rect.get("stroke-width"))
    assert x - sw / 2 == pytest.approx(130) and (x + w + sw / 2) == pytest.approx(470)


def test_html_mirrors_the_tree_and_css_is_relative_to_parent(doc):
    html = render_html(doc)
    assert html.startswith("<!doctype html>")
    assert html.count("data-sf-id=") == len(doc.components)
    i_card, i_input = html.index('id="sf-card-1"'), html.index('id="sf-input-1"')
    assert i_card < i_input < html.index("</section>")  # input is nested inside the card element
    css = render_css(doc)
    assert "#sf-input-1 { left:30px; top:70px; width:340px; height:44px" in css  # relative to card
    assert "<script" not in html.lower()


def test_raster_snapshot_geometry_and_colours(doc):
    img = render_image(doc)
    assert img.shape == (600, 600, 3) and img.dtype == np.uint8
    b, g, r = img[464, 160]  # inside the primary-coloured button, away from its label
    assert (r, g, b) == (0x25, 0x63, 0xEB)
    assert tuple(img[580, 580]) == (255, 255, 255)  # page background
    assert render_image(doc, scale=0.5).shape == (300, 300, 3)
    png = render_png_bytes(doc)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_moving_a_component_changes_pixels_there(doc):
    before = render_image(doc)
    UndoStack(doc).execute(MoveCommand("button-1", 0, 30))
    after = render_image(doc)
    assert (before != after).any()
    assert tuple(before[464, 160]) != tuple(after[464, 160]) or tuple(before[500, 160]) != tuple(after[500, 160])


def test_render_all_saves_every_format(doc, tmp_path):
    r = render_all(doc, highlights={"button-1": "#ff0000"})
    paths = r.save(tmp_path, "form")
    assert all(p.exists() and p.stat().st_size > 0 for p in paths.values())
    assert r.document_hash == document_hash(doc)
    assert 'stroke="#ff0000"' in r.svg


@pytest.mark.ui
def test_qt_can_load_and_rasterize_the_svg(doc):
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(render_svg(doc).encode())
    assert renderer.isValid()
    image = QImage(600, 600, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    color = image.pixelColor(160, 464)
    assert (color.red(), color.green(), color.blue()) == (0x25, 0x63, 0xEB)
    assert app is not None
