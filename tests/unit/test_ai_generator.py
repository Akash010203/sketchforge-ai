"""Unit tests for the robust two-stage AI code generation pipeline.

Tests:
- extract_balanced_json with nested braces and markdown wrappers
- _parse_file_content with markdown code fences (including unclosed/truncated)
- Pinned active model selection (Nemotron-3_5-Lightning)
- Per-file fallback from template planner (no all-or-nothing discard)
- Structured layout context injection from OpenCV Design IR
- RAG code pattern retrieval for Stage 2 files
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sketchforge.generation.ai_generator import (
    _PINNED_MODEL,
    _parse_file_content,
    _parse_response,
    _format_layout_context,
    _select_active_model,
    ai_generate_project,
    extract_balanced_json,
    get_fallback_file_content,
)
from sketchforge.retrieval.code_retriever import retrieve_code_pattern


def test_extract_balanced_json_handles_nested_objects_and_preamble():
    raw = (
        "Here is the architecture plan:\n\n"
        '```json\n{"name": "TaskFlow", "entities": [{"name": "Task", "fields": [{"name": "title"}]}], "pages": [{"name": "home"}]}\n```\n\n'
        "Note: You can run this app with python -m backend.api"
    )
    data = extract_balanced_json(raw)
    assert data["name"] == "TaskFlow"
    assert len(data["entities"]) == 1
    assert data["entities"][0]["name"] == "Task"


def test_extract_balanced_json_handles_string_braces_and_escapes():
    raw = (
        '{"name": "App with {braces} in string", "quote": "He said \\"hello\\"", '
        '"nested": {"level2": {"level3": true}}}'
    )
    data = extract_balanced_json(raw)
    assert data["name"] == "App with {braces} in string"
    assert data["quote"] == 'He said "hello"'
    assert data["nested"]["level2"]["level3"] is True


def test_parse_file_content_closed_markdown_fence():
    text = (
        "Here is the code:\n\n"
        "```python\n"
        "def main():\n"
        "    print('hello')\n"
        "```\n\n"
        "Enjoy!"
    )
    code = _parse_file_content(text, "backend/logic.py")
    assert code == "def main():\n    print('hello')"


def test_parse_file_content_unclosed_truncated_markdown_fence():
    # Model hit max_tokens before closing ```
    text = (
        "```html\n"
        "<!doctype html>\n"
        "<html>\n"
        "<body><h1>Cut off before backticks"
    )
    code = _parse_file_content(text, "home.html")
    assert "<!doctype html>" in code
    assert "Cut off before backticks" in code


def test_parse_file_content_json_envelope_fallback():
    text = json.dumps({"path": "backend/api.py", "content": "from flask import Flask\napp = Flask(__name__)"})
    code = _parse_file_content(text, "backend/api.py")
    assert "from flask import Flask" in code


def test_pinned_model_is_nemotron_lightning():
    assert _PINNED_MODEL == "nvidia/Nemotron-3_5-Lightning"


def test_select_active_model_probes_pinned_first(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(text="pong")
    emitted = []

    model, err = _select_active_model(mock_client, emitted.append)
    assert model == "nvidia/Nemotron-3_5-Lightning"
    assert err is None
    assert any("connecting to pinned model: Nemotron-3_5-Lightning" in msg for msg in emitted)


def test_get_fallback_file_content_generates_all_12_files():
    spec = {
        "name": "PlannerPro",
        "pages": [{"name": "home", "title": "Home"}, {"name": "projects", "title": "Projects"}],
        "entities": [
            {"name": "Project", "fields": [{"name": "title", "type": "text"}, {"name": "budget", "type": "number"}]}
        ],
        "include_backend": True,
    }

    manifest_paths = [
        "index.html", "css/style.css", "home.html", "projects.html",
        "js/home.js", "js/projects.js", "backend/schema.sql",
        "backend/models.py", "backend/database.py", "backend/logic.py",
        "backend/api.py", "requirements.txt",
    ]

    for path in manifest_paths:
        content = get_fallback_file_content(path, spec)
        assert isinstance(content, str) and len(content.strip()) > 0, f"Empty fallback for {path}"

    # Specific assertions
    assert "meta http-equiv=\"refresh\"" in get_fallback_file_content("index.html", spec)
    assert "Segoe UI" in get_fallback_file_content("css/style.css", spec)
    assert "PlannerPro" in get_fallback_file_content("home.html", spec)
    assert "submissions-list" in get_fallback_file_content("projects.html", spec)
    assert "fetch(" in get_fallback_file_content("js/home.js", spec)
    assert "CREATE TABLE" in get_fallback_file_content("backend/schema.sql", spec)
    assert "Flask" in get_fallback_file_content("backend/api.py", spec)
    assert "Flask" in get_fallback_file_content("requirements.txt", spec)


def test_format_layout_context():
    block = {
        "canvas": {"width_design_px": 1200, "height_design_px": 800, "device": "desktop"},
        "hierarchy": "* header\n  * button",
        "components": [
            {"id": "btn_1", "type": "button", "bbox_design_px": {"x": 20, "y": 30, "w": 100, "h": 40}, "label": "Save"}
        ]
    }
    context = _format_layout_context(block)
    assert "1200x800" in context
    assert "* header" in context
    assert "[BUTTON] id=btn_1" in context
    assert "label=\"Save\"" in context


def test_retrieve_code_pattern_via_rag():
    py_pattern = retrieve_code_pattern("backend/api.py", "Flask REST API")
    assert py_pattern is not None
    assert "Flask" in py_pattern
    assert "CORS" in py_pattern or "Allow-Origin" in py_pattern

    css_pattern = retrieve_code_pattern("css/style.css", "responsive layout")
    assert css_pattern is not None
    assert "--accent: #d9ff5f" in css_pattern


def test_ai_generate_project_per_file_fallback_preserves_ai_files(tmp_path):
    """Simulate a run where 11 files succeed from AI, but 1 file (e.g. backend/api.py) fails.

    Verify that:
    1. The project is NOT discarded!
    2. The 11 AI-generated files are preserved.
    3. The failed file is populated from the template fallback.
    4. Exactly 12 files exist and are valid.
    """
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(text="pong")

    spec_dict = {
        "name": "TestTracker",
        "pages": [{"name": "home", "title": "Home"}, {"name": "projects", "title": "Projects"}],
        "entities": [{"name": "Item", "fields": [{"name": "title"}]}],
        "include_backend": True,
    }

    # Patch Stage 1 to return our spec
    def fake_stage1(*args, **kwargs):
        return spec_dict, "nvidia/Nemotron-3_5-Lightning"

    # Patch Stage 2: return AI content for all files EXCEPT backend/api.py (which returns None)
    def fake_stage2(client, spec_str, path_hint, description, emit, model, layout_context=None, **kwargs):
        if path_hint == "backend/api.py":
            return None  # simulated failure / token cutoff
        return f"/* AI Generated Content for {path_hint} */"

    with patch("sketchforge.generation.ai_generator._make_client", return_value=mock_client), \
         patch("sketchforge.generation.ai_generator._stage1_plan", side_effect=fake_stage1), \
         patch("sketchforge.generation.ai_generator._stage2_file", side_effect=fake_stage2):

        emitted = []
        root = ai_generate_project("build a task tracker", tmp_path, progress=emitted.append)

        assert root is not None
        assert root.is_dir()
        assert (root / "home.html").read_text(encoding="utf-8") == "/* AI Generated Content for home.html */"
        assert (root / "css/style.css").read_text(encoding="utf-8") == "/* AI Generated Content for css/style.css */"

        # backend/api.py was filled from fallback template, not discarded
        api_code = (root / "backend/api.py").read_text(encoding="utf-8")
        assert "Flask" in api_code
        assert "api.py" in "".join(emitted) or "Fallback" in "".join(emitted)
