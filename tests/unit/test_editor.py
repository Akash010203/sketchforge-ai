import pytest

from sketchforge.design_ir import BBox, Component, ComponentType, document_hash, validate_document
from sketchforge.editor import (
    AddComponentCommand,
    CompositeCommand,
    MoveCommand,
    RemoveComponentCommand,
    ReparentCommand,
    SetBBoxCommand,
    SetStyleCommand,
    SetTextCommand,
    SetTypographyCommand,
    UndoStack,
    hit_test,
    make_edit,
)
from sketchforge.editor.layer_operations import reorder
from sketchforge.editor.selection import Selection, components_in_rect
from sketchforge.exceptions import EditError
from support import make_form_document


@pytest.fixture
def doc():
    return make_form_document()


def test_every_command_is_exactly_reversible(doc):
    before = document_hash(doc)
    stack = UndoStack(doc)
    new_comp = Component(id="text-9", type=ComponentType.TEXT, parent_id="card-1",
                         bbox=BBox(x=140, y=500, w=100, h=20), text="hi")
    commands = [
        SetTextCommand("heading-1", "Welcome"),
        SetStyleCommand("button-1", fill="#ff0000", corner_radius=12),
        SetTypographyCommand("heading-1", font_size=30, font_weight=800),
        MoveCommand("card-1", 13.37, -7.123),
        SetBBoxCommand("input-1", BBox(x=131, y=171, w=300, h=40)),
        AddComponentCommand(new_comp),
        RemoveComponentCommand("input-2"),
        ReparentCommand("input-3", "page"),
    ]
    for cmd in commands:
        stack.execute(cmd)
    after = document_hash(doc)
    assert after != before
    while stack.can_undo:
        stack.undo()
    assert document_hash(doc) == before
    while stack.can_redo:
        stack.redo()
    assert document_hash(doc) == after
    assert validate_document(doc).ok


def test_move_translates_the_whole_subtree(doc):
    stack = UndoStack(doc)
    child_before = doc.require("input-1").bbox
    stack.execute(MoveCommand("card-1", 10, 20))
    child_after = doc.require("input-1").bbox
    assert (child_after.x, child_after.y) == (child_before.x + 10, child_before.y + 20)
    assert doc.require("card-1").bbox.x == 110


def test_invalid_edit_leaves_document_untouched(doc):
    stack = UndoStack(doc)
    before = document_hash(doc)
    for bad in (
        SetStyleCommand("button-1", fill="red"),            # not a hex colour
        SetStyleCommand("button-1", opacity=2.0),           # out of range
        SetTypographyCommand("heading-1", font_size=1),     # below minimum
        SetTextCommand("header-1", "text on a container"),  # type carries no text
        SetBBoxCommand("page", BBox(x=0, y=0, w=10, h=10)),  # the page box is derived
        MoveCommand("nope", 1, 1),
    ):
        with pytest.raises(EditError):
            stack.execute(bad)
    assert document_hash(doc) == before
    assert not stack.can_undo


def test_locked_and_non_editable_components_are_protected(doc):
    doc.require("button-1").locked = True
    stack = UndoStack(doc)
    with pytest.raises(EditError, match="locked"):
        stack.execute(SetTextCommand("button-1", "x"))
    with pytest.raises(EditError, match="locked"):
        stack.execute(MoveCommand("card-1", 5, 5))  # card contains a locked child
    doc.require("button-1").locked = False
    doc.require("heading-1").editable = ["text"]
    with pytest.raises(EditError, match="does not allow"):
        stack.execute(SetStyleCommand("heading-1", fill="#ffffff"))
    cmd = SetStyleCommand("heading-1", fill="#ffffff")
    cmd.respect_locks = False  # repair/system edits may opt out
    stack.execute(cmd)


def test_composite_is_atomic(doc):
    stack = UndoStack(doc)
    before = document_hash(doc)
    composite = CompositeCommand(
        [SetTextCommand("heading-1", "A"), SetStyleCommand("button-1", fill="bad")], "two edits")
    with pytest.raises(EditError):
        stack.execute(composite)
    assert document_hash(doc) == before
    ok = CompositeCommand([SetTextCommand("heading-1", "A"), SetTextCommand("button-1", "B")], "two edits")
    stack.execute(ok)
    stack.undo()
    assert document_hash(doc) == before


def test_new_edit_clears_redo(doc):
    stack = UndoStack(doc)
    stack.execute(SetTextCommand("heading-1", "A"))
    stack.undo()
    assert stack.can_redo
    stack.execute(SetTextCommand("heading-1", "B"))
    assert not stack.can_redo
    with pytest.raises(EditError):
        stack.redo()


def test_user_text_is_no_longer_inferred(doc):
    comp = doc.require("heading-1")
    comp.text_is_inferred = True
    UndoStack(doc).execute(SetTextCommand("heading-1", "Real title"))
    assert comp.text == "Real title" and comp.text_is_inferred is False


def test_make_edit_parses_user_values(doc):
    stack = UndoStack(doc)
    stack.execute(make_edit(doc, "button-1", "fill", "#F00"))
    assert doc.require("button-1").style.fill == "#ff0000"
    stack.execute(make_edit(doc, "button-1", "x", "140"))
    assert doc.require("button-1").bbox.x == 140
    stack.execute(make_edit(doc, "button-1", "width", "300"))
    assert doc.require("button-1").bbox.w == 300
    stack.execute(make_edit(doc, "heading-1", "font_size", "28"))
    assert doc.require("heading-1").typography.font_size == 28
    stack.execute(make_edit(doc, "heading-1", "text", "Hello"))
    assert doc.require("heading-1").text == "Hello"
    for prop, value in (("fill", "salmon"), ("width", "-5"), ("width", "abc"), ("bogus", 1), ("x", "nan")):
        with pytest.raises(EditError):
            stack.execute(make_edit(doc, "button-1", prop, value))
    assert validate_document(doc).ok


def test_history_records_actions(doc):
    stack = UndoStack(doc)
    stack.execute(SetTextCommand("heading-1", "A"))
    stack.undo()
    stack.redo()
    kinds = [r.kind for r in stack.history.records]
    assert kinds == ["do", "undo", "redo"]
    assert stack.revision == 3


def test_hit_test_picks_deepest_topmost(doc):
    assert hit_test(doc, 140, 180).id == "input-1"
    assert hit_test(doc, 110, 110).id == "card-1"
    assert hit_test(doc, 5, 590) is None
    assert hit_test(doc, 5, 590, include_root=True).id == "page"
    doc.require("input-1").visible = False
    assert hit_test(doc, 140, 180).id == "card-1"


def test_selection_and_rect_select(doc):
    sel = Selection()
    sel.set(["a", "b", "a"])
    assert sel.ids == ("a", "b") and sel.primary == "b"
    sel.toggle("a")
    assert sel.ids == ("b",)
    sel.prune(doc)
    assert sel.ids == ()
    inside = components_in_rect(doc, BBox(x=100, y=100, w=400, h=190))
    assert {c.id for c in inside} == {"heading-1", "input-1", "input-2"}


def test_reorder_renumbers_siblings(doc):
    stack = UndoStack(doc)
    stack.execute(reorder(doc, "input-1", "front"))
    assert doc.children_ids("card-1")[-1] == "input-1"
    stack.undo()
    assert doc.children_ids("card-1")[0] == "heading-1"
