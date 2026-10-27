"""End-to-end check: generate a Python backend, run its generated tests in a sandbox."""

from __future__ import annotations

from sketchforge.execution.environment_manager import copy_project_files
from sketchforge.execution.sandbox import open_sandbox
from sketchforge.generation.app_specification import AppSpec, EntitySpec, FieldSpec
from sketchforge.generation.backend.business_logic_generator import generate_logic_py
from sketchforge.generation.backend.database_generator import generate_database_py
from sketchforge.generation.backend.schema_generator import generate_models_py, generate_schema_sql
from sketchforge.generation.backend.test_generator import generate_test_py
from sketchforge.verification.project_inspector import inspect_project
from sketchforge.verification.test_runner import run_tests


def test_generated_backend_tests_execute_and_artifacts_are_verified(tmp_path):
    spec = AppSpec(
        name="TaskBoard",
        description="A generated task tracker",
        tech_backend="python-sqlite",
        entities=[
            EntitySpec(
                name="Task",
                fields=[
                    FieldSpec(name="title", label="Title", type="text"),
                    FieldSpec(name="priority", label="Priority", type="number"),
                ],
            )
        ],
    )
    generated_files = {
        "backend/__init__.py": "",
        "backend/schema.sql": generate_schema_sql(spec),
        "backend/models.py": generate_models_py(spec),
        "backend/database.py": generate_database_py(spec),
        "backend/logic.py": generate_logic_py(spec),
        "backend/tests/test_generated_crud.py": generate_test_py(spec),
    }

    with open_sandbox(base_dir=tmp_path, env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}) as session:
        project_root = session.root / "project"
        project_root.mkdir()
        copy_project_files(generated_files, project_root)

        inspection = inspect_project(project_root)
        test_result = run_tests(session, project_root)

        assert inspection["stack"] == "html-css-js"
        assert inspection["total_files"] == len(generated_files)
        assert (project_root / "backend" / "database.py").is_file()
        assert test_result.ok, f"stdout:\n{test_result.stdout}\nstderr:\n{test_result.stderr}"
        assert "1 passed" in test_result.stdout
        assert not list(project_root.glob("data/*")), "sandboxed tests must not write a host database"
