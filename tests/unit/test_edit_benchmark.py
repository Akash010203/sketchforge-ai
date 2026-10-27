import json
import pytest
from sketchforge.assist.edit_benchmark import (
    load_tasks,
    oracle_plan,
    local_plan,
    run_benchmark,
    _matches,
)
from sketchforge.design_ir import (
    BBox,
    Component,
    ComponentType,
    Style,
    add_component,
    new_document,
)


@pytest.fixture
def mini_doc():
    doc = new_document("test_page", 800, 600)
    add_component(
        doc,
        Component(
            id="btn-1",
            type=ComponentType.BUTTON,
            parent_id="page",
            bbox=BBox(x=100, y=100, w=120, h=40),
            text="Submit",
            style=Style(fill="#000000", stroke="#333333"),
        ),
    )
    return doc


def test_matches_evaluates_checks(mini_doc):
    checks = [{"id": "btn-1", "text": "Submit", "fill": "#000000"}]
    ok, errors = _matches(mini_doc, checks)
    assert ok
    assert not errors

    bad_checks = [{"id": "btn-1", "text": "Cancel"}]
    bad_ok, bad_errors = _matches(mini_doc, bad_checks)
    assert not bad_ok
    assert len(bad_errors) == 1


def test_load_tasks_validates_structure(tmp_path):
    p = tmp_path / "tasks.json"
    p.write_text(json.dumps({"tasks": [{"id": "t1"}, {"id": "t2"}]}))
    data = load_tasks(p)
    assert len(data["tasks"]) == 2

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"tasks": [{"id": "t1"}, {"id": "t1"}]}))
    with pytest.raises(ValueError, match="unique"):
        load_tasks(bad)


def test_run_benchmark_with_in_memory_docs(mini_doc):
    benchmark_data = {
        "fixture": {"layouts": [], "seed": 1},
        "tasks": [
            {
                "id": "t01",
                "doc": "test_page",
                "category": "color",
                "instruction": "make the button blue",
                "reference": {
                    "ops": [{"op": "set_fill", "target": "btn-1", "color": "blue"}]
                },
                "expect": {
                    "kind": "edit",
                    "checks": [{"id": "btn-1", "fill": "blue"}],
                    "no_new_issues": False,
                },
            },
            {
                "id": "t02",
                "doc": "test_page",
                "category": "refusal",
                "instruction": "launch the rocket",
                "reference": None,
                "expect": {"kind": "refuse"},
            },
        ],
    }

    result = run_benchmark(
        benchmark_data,
        arms=("oracle", "local"),
        docs={"test_page": mini_doc},
    )

    assert result["version"] == 1
    assert "oracle" in result["summary"]
    assert "local" in result["summary"]
    assert result["summary"]["oracle"]["passed"] == 2
    assert result["summary"]["oracle"]["pass_rate"] == 1.0
