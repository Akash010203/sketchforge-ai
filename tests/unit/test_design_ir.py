import json
from unittest.mock import patch

import pytest

from sketchforge.constants import SCHEMA_VERSION
from sketchforge.design_ir import (
    BBox,
    Component,
    ComponentType,
    add_component,
    ancestors_of,
    descendants_of,
    document_hash,
    from_dict,
    from_json,
    load_document,
    make_component_id,
    move_subtree,
    new_document,
    preorder,
    remove_subtree,
    reparent,
    restore_components,
    save_document,
    to_dict,
    to_json,
    validate_document,
)
from sketchforge.design_ir.migrations import Migrator, parse_version
from sketchforge.exceptions import DesignValidationError, MigrationError, SketchForgeError


def comp(cid, parent, x, y, w, h, ctype=ComponentType.CONTAINER, **kw):
    return Component(id=cid, type=ctype, parent_id=parent, bbox=BBox(x=x, y=y, w=w, h=h), **kw)


@pytest.fixture
def doc():
    d = new_document("t", 400, 300)
    add_component(d, comp("card-1", "page", 20, 20, 200, 200, ComponentType.CARD))
    add_component(d, comp("btn-1", "card-1", 30, 150, 100, 40, ComponentType.BUTTON, text="Go"))
    add_component(d, comp("txt-1", "card-1", 30, 30, 100, 20, ComponentType.TEXT, text="Hi"))
    return d


# ---------------------------------------------------------------------------- construction
def test_new_document_has_only_root():
    d = new_document("x", 800, 600)
    assert [c.id for c in d.components] == ["page"]
    assert d.root.type is ComponentType.PAGE
    assert d.root.bbox == BBox(x=0, y=0, w=800, h=600)
    assert validate_document(d).ok


def test_component_schema_rejects_bad_input():
    with pytest.raises(ValueError):
        comp("Bad Id!", "page", 0, 0, 1, 1)
    with pytest.raises(ValueError):
        Component(id="a", type="nonsense", bbox=BBox(x=0, y=0, w=1, h=1))
    with pytest.raises(ValueError):
        comp("a", "page", 0, 0, 1, 1).model_validate({"id": "a", "type": "text", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}, "bogus": 1})


def test_colors_are_validated_and_normalized(doc):
    c = doc.require("btn-1")
    c.style.fill = "#ABCDEF"
    assert c.style.fill == "#abcdef"
    with pytest.raises(ValueError):
        c.style.fill = "red"
    with pytest.raises(ValueError):
        c.style.opacity = 1.5


def test_assignment_is_validated(doc):
    c = doc.require("btn-1")
    with pytest.raises(ValueError):
        c.id = "NOT valid"


def test_add_component_rejects_duplicates_and_missing_parent(doc):
    with pytest.raises(SketchForgeError):
        add_component(doc, comp("btn-1", "page", 0, 0, 5, 5))
    with pytest.raises(SketchForgeError):
        add_component(doc, comp("new-1", "ghost", 0, 0, 5, 5))


def test_make_component_id_is_deterministic_and_unique(doc):
    assert make_component_id(doc, "btn") == "btn-2"
    assert make_component_id(doc, "Brand New!") == "brand-new-1"
    assert make_component_id(doc, "9lives") == "c-9lives-1"


# ---------------------------------------------------------------------------- tree ops
def test_tree_queries(doc):
    assert [c.id for c in doc.children_of("card-1")] == ["btn-1", "txt-1"]
    assert [c.id for c in descendants_of(doc, "page")] == ["card-1", "btn-1", "txt-1"]
    assert [c.id for c in ancestors_of(doc, "btn-1")] == ["card-1", "page"]
    assert [c.id for c in preorder(doc)] == ["page", "card-1", "btn-1", "txt-1"]


def test_children_order_follows_z_index_then_insertion(doc):
    doc.require("txt-1").z_index = -1
    doc.invalidate_index()
    assert doc.children_ids("card-1") == ["txt-1", "btn-1"]


def test_move_subtree_moves_descendants(doc):
    move_subtree(doc, "card-1", 10, 5)
    assert doc.require("card-1").bbox == BBox(x=30, y=25, w=200, h=200)
    assert doc.require("btn-1").bbox == BBox(x=40, y=155, w=100, h=40)


def test_remove_and_restore_subtree_round_trips_order(doc):
    before = to_json(doc)
    removed = remove_subtree(doc, "card-1")
    assert [c.id for _, c in removed] == ["card-1", "btn-1", "txt-1"]
    assert doc.get("btn-1") is None
    restore_components(doc, removed)
    assert to_json(doc) == before


def test_cannot_remove_root(doc):
    with pytest.raises(SketchForgeError):
        remove_subtree(doc, "page")


def test_reparent_rules(doc):
    add_component(doc, comp("card-2", "page", 240, 20, 100, 100, ComponentType.CARD))
    reparent(doc, "txt-1", "card-2")
    assert [c.id for c in doc.children_of("card-2")] == ["txt-1"]
    with pytest.raises(SketchForgeError):
        reparent(doc, "card-1", "btn-1")  # under own descendant
    with pytest.raises(SketchForgeError):
        reparent(doc, "page", "card-1")


# ---------------------------------------------------------------------------- validation
def test_valid_document_has_no_errors(doc):
    report = validate_document(doc)
    assert report.ok, report.errors


def test_detects_missing_parent_and_duplicate_ids(doc):
    doc.components.append(comp("orphan-1", "nobody", 0, 0, 5, 5))
    doc.components.append(comp("btn-1", "page", 0, 0, 5, 5))
    doc.invalidate_index()
    report = validate_document(doc)
    assert not report.ok
    assert {"E_PARENT_MISSING", "E_DUPLICATE_ID"} <= report.codes()
    with pytest.raises(DesignValidationError):
        report.raise_if_invalid()


def test_detects_cycle(doc):
    doc.require("card-1").parent_id = "btn-1"
    doc.invalidate_index()
    assert "E_CYCLE" in validate_document(doc).codes()


def test_detects_second_page_and_two_roots(doc):
    add_component(doc, comp("pg-2", "page", 0, 0, 10, 10, ComponentType.PAGE))
    assert "E_PAGE_NOT_ROOT" in validate_document(doc).codes()
    doc.require("pg-2").parent_id = None
    doc.invalidate_index()
    assert "E_ROOT_COUNT" in validate_document(doc).codes()


def test_overflow_and_outside_page_are_warnings_not_errors(doc):
    doc.require("btn-1").bbox = BBox(x=180, y=150, w=100, h=40)  # sticks out of the card
    doc.require("txt-1").bbox = BBox(x=380, y=30, w=100, h=20)  # sticks out of the page
    report = validate_document(doc)
    assert report.ok
    assert {"W_OVERFLOW_PARENT", "W_OUTSIDE_PAGE"} <= report.codes()


def test_completely_outside_page_is_an_error(doc):
    doc.require("txt-1").bbox = BBox(x=900, y=900, w=10, h=10)
    assert "E_OUTSIDE_PAGE" in validate_document(doc).codes()


def test_text_on_divider_warns(doc):
    add_component(doc, comp("hr-1", "page", 0, 250, 300, 2, ComponentType.DIVIDER, text="oops"))
    assert "W_TEXT_ON_NON_TEXT" in validate_document(doc).codes()


# ---------------------------------------------------------------------------- serialization
def test_json_round_trip_is_lossless_and_deterministic(doc):
    text = to_json(doc)
    again = from_json(text)
    assert again == doc
    assert to_json(again) == text
    assert document_hash(again) == document_hash(doc)
    json.loads(text)  # really JSON


def test_hash_changes_with_content(doc):
    h1 = document_hash(doc)
    doc.require("txt-1").text = "Changed"
    assert document_hash(doc) != h1


def test_save_and_load(tmp_path, doc):
    path = save_document(doc, tmp_path / "sub" / "design.json")
    assert path.exists()
    assert load_document(path) == doc
    assert not list(path.parent.glob(".*.tmp"))  # atomic write cleaned up


def test_save_falls_back_when_windows_sandbox_blocks_rename(tmp_path, doc):
    path = tmp_path / "design.json"
    with patch("os.replace", side_effect=PermissionError):
        save_document(doc, path)
    assert load_document(path) == doc
    assert not list(path.parent.glob(".*.tmp"))


def test_load_rejects_garbage(tmp_path):
    with pytest.raises(DesignValidationError):
        from_json("{not json")
    with pytest.raises(DesignValidationError):
        from_dict({"schema_version": SCHEMA_VERSION, "document_id": "x"})


def test_snapshot_and_restore(doc):
    snap = doc.snapshot()
    doc.require("btn-1").text = "Mutated"
    remove_subtree(doc, "txt-1")
    doc.restore(snap)
    assert doc.require("btn-1").text == "Go"
    assert doc.get("txt-1") is not None
    assert validate_document(doc).ok


# ---------------------------------------------------------------------------- migrations
def test_version_parsing():
    assert parse_version("1.2.3") == (1, 2, 3)
    with pytest.raises(MigrationError):
        parse_version("1.2")


def test_current_version_passes_through(doc):
    assert from_dict(to_dict(doc)) == doc


def test_newer_and_missing_versions_are_rejected(doc):
    data = to_dict(doc)
    data["schema_version"] = "99.0.0"
    with pytest.raises(MigrationError):
        from_dict(data)
    data.pop("schema_version")
    with pytest.raises(MigrationError):
        from_dict(data)


def test_unknown_old_version_has_no_path(doc):
    data = to_dict(doc)
    data["schema_version"] = "0.0.1"
    with pytest.raises(MigrationError, match="no migration path"):
        from_dict(data)


def test_migration_chain_runs_in_order_without_mutating_input():
    m = Migrator(target="1.2.0")

    @m.register("1.0.0", "1.1.0")
    def _a(d):
        d["steps"] = [*d.get("steps", []), "a"]
        return d

    @m.register("1.1.0", "1.2.0")
    def _b(d):
        d["steps"] = [*d.get("steps", []), "b"]
        return d

    original = {"schema_version": "1.0.0"}
    out = m.migrate(original)
    assert out == {"schema_version": "1.2.0", "steps": ["a", "b"]}
    assert original == {"schema_version": "1.0.0"}


def test_migration_registration_guards():
    m = Migrator(target="2.0.0")
    with pytest.raises(MigrationError):
        m.register("1.0.0", "1.0.0")
    m.register("1.0.0", "2.0.0")(lambda d: d)
    with pytest.raises(MigrationError):
        m.register("1.0.0", "2.0.0")(lambda d: d)
