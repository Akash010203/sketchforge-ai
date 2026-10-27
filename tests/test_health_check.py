"""Fast import and template sanity checks for the CLI, UI, and backend generators."""
from __future__ import annotations

import ast
import importlib

from sketchforge.__main__ import build_parser
from sketchforge.generation.app_specification import AppSpec, EntitySpec, FieldSpec, PageSpec
from sketchforge.generation.backend.schema_generator import render_backend_file
from sketchforge.generation.project_planner import plan_react_ts


def test_cli_and_ui_modules_load():
    parser = build_parser()
    assert parser.prog == "sketchforge"
    # The application bootstrap defers Qt imports, so this also works in CLI-only installs.
    importlib.import_module("sketchforge.app")
    importlib.import_module("sketchforge.ui.main_window")


def test_generated_backend_templates_load_and_compile():
    spec = AppSpec(
        name="Health Check",
        pages=[PageSpec(name="home", title="Home", route="/")],
        entities=[EntitySpec("Submission", [FieldSpec("email", "Email", "email")])],
        tech_frontend="react-ts",
        tech_backend="python-sqlite",
    )
    plan = plan_react_ts(spec)
    backend_files = [item for item in plan.files if item.generator.startswith("backend_")]
    assert backend_files
    for planned_file in backend_files:
        source = render_backend_file(planned_file, plan)
        if planned_file.relative_path.endswith(".py"):
            ast.parse(source, filename=planned_file.relative_path)
