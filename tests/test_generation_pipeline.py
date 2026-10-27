"""Tests for the generation pipeline: project planner, component/page/style generators, validation."""
from __future__ import annotations

import pytest
from pathlib import Path

from sketchforge.generation.app_specification import AppSpec, PageSpec, FieldSpec, ActionSpec, EntitySpec
from sketchforge.generation.project_planner import make_plan, plan_react_ts, plan_html_css
from sketchforge.generation.frontend.component_generator import generate_component
from sketchforge.generation.frontend.page_generator import generate_page
from sketchforge.generation.frontend.style_generator import global_css, generate_page_css, all_component_css_files
from sketchforge.generation.frontend.project_export import render_file
from sketchforge.generation.validation import validate_text, validate_bundle
from sketchforge.generation.backend.schema_generator import (
    generate_schema_sql, generate_models_py, generate_database_py, generate_logic_py
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_spec() -> AppSpec:
    return AppSpec(
        name="TestApp",
        pages=[
            PageSpec(
                name="home",
                title="Home",
                route="/",
                components=[{"type": "button"}, {"type": "input"}, {"type": "card"}],
                forms=[[
                    FieldSpec(name="email", label="Email", type="email", required=True),
                    FieldSpec(name="password", label="Password", type="password", required=True),
                ]],
                actions=[ActionSpec(label="Sign In", action="submit_form")],
            )
        ],
        requires_auth=False,
        tech_frontend="react-ts",
        tech_backend="none",
    )


@pytest.fixture
def multi_page_spec() -> AppSpec:
    return AppSpec(
        name="Dashboard",
        pages=[
            PageSpec(name="login", title="Login", route="/login"),
            PageSpec(name="dashboard", title="Dashboard", route="/dashboard"),
            PageSpec(name="settings", title="Settings", route="/settings"),
        ],
        tech_frontend="react-ts",
        tech_backend="python-sqlite",
        entities=[
            EntitySpec(
                name="User",
                primary_key="id",
                fields=[
                    FieldSpec(name="email", label="Email", type="email", required=True),
                    FieldSpec(name="name", label="Name", type="text"),
                ],
                timestamps=True,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Project planner tests
# ---------------------------------------------------------------------------

class TestProjectPlanner:

    def test_make_plan_react(self, simple_spec):
        plan = make_plan(simple_spec)
        assert plan.tech_frontend == "react-ts"
        paths = plan.paths()
        assert "package.json" in paths
        assert "src/main.tsx" in paths
        assert "src/App.tsx" in paths
        assert "src/styles/global.css" in paths

    def test_plan_contains_page_files(self, simple_spec):
        plan = make_plan(simple_spec)
        assert "src/pages/Home.tsx" in plan.paths()
        assert "src/styles/home.module.css" in plan.paths()

    def test_plan_contains_component_files(self, simple_spec):
        plan = make_plan(simple_spec)
        paths = plan.paths()
        # button, input, card detected from spec
        assert any("Button.tsx" in p for p in paths)
        assert any("Input.tsx" in p for p in paths)
        assert any("Card.tsx" in p for p in paths)

    def test_backend_files_present_when_requested(self, multi_page_spec):
        plan = make_plan(multi_page_spec)
        paths = plan.paths()
        assert "backend/models.py" in paths
        assert "backend/database.py" in paths
        assert "backend/schema.sql" in paths
        assert "backend/logic.py" in paths

    def test_html_css_plan(self, simple_spec):
        simple_spec.tech_frontend = "html-css-js"
        plan = plan_html_css(simple_spec)
        assert plan.tech_frontend == "html-css-js"
        assert "css/style.css" in plan.paths()
        assert "home.html" in plan.paths()

    def test_by_generator(self, simple_spec):
        plan = make_plan(simple_spec)
        pages = plan.by_generator("page")
        assert len(pages) == 1
        assert pages[0].relative_path == "src/pages/Home.tsx"

    def test_readme_present(self, simple_spec):
        plan = make_plan(simple_spec)
        assert "README.md" in plan.paths()

    def test_multi_page_routing(self, multi_page_spec):
        plan = make_plan(multi_page_spec)
        paths = plan.paths()
        assert "src/pages/Login.tsx" in paths
        assert "src/pages/Dashboard.tsx" in paths
        assert "src/pages/Settings.tsx" in paths


# ---------------------------------------------------------------------------
# Component generator tests
# ---------------------------------------------------------------------------

class TestComponentGenerator:

    @pytest.mark.parametrize("ctype", [
        "button", "input", "card", "header", "nav",
        "text", "image", "checkbox", "divider",
    ])
    def test_known_components_generate_tsx(self, ctype):
        code = generate_component(ctype)
        assert "import React" in code
        assert f"const " in code
        assert "export default" in code

    def test_button_has_props(self):
        code = generate_component("button", {"label": "Submit"})
        assert "ButtonProps" in code
        assert "onClick" in code
        assert "disabled" in code

    def test_input_has_error_state(self):
        code = generate_component("input")
        assert "error" in code
        assert "required" in code

    def test_unknown_component_generates_generic(self):
        code = generate_component("unknown_widget_xyz")
        assert "React.FC" in code
        assert "export default" in code

    def test_nav_uses_react_router(self):
        code = generate_component("nav")
        assert "NavLink" in code or "react-router-dom" in code


# ---------------------------------------------------------------------------
# Page generator tests
# ---------------------------------------------------------------------------

class TestPageGenerator:

    def test_generates_valid_tsx(self, simple_spec):
        page = simple_spec.pages[0]
        code = generate_page(page)
        assert "import React" in code
        assert "const Home: React.FC" in code
        assert "export default Home" in code

    def test_form_state_generated(self, simple_spec):
        page = simple_spec.pages[0]
        code = generate_page(page)
        assert "FormState" in code
        assert "email" in code
        assert "password" in code

    def test_form_validation(self, simple_spec):
        page = simple_spec.pages[0]
        code = generate_page(page)
        assert "handleSubmit" in code
        assert "required" in code.lower()

    def test_page_title_in_jsx(self, simple_spec):
        page = simple_spec.pages[0]
        code = generate_page(page)
        assert "Home" in code


# ---------------------------------------------------------------------------
# Style generator tests
# ---------------------------------------------------------------------------

class TestStyleGenerator:

    def test_global_css_has_tokens(self):
        css = global_css()
        assert "--sf-primary" in css
        assert "--sf-font" in css
        assert "box-sizing" in css

    def test_component_css_all_present(self):
        files = all_component_css_files()
        expected = ["Button.module.css", "Input.module.css", "Card.module.css",
                    "Nav.module.css", "Header.module.css"]
        for f in expected:
            assert f in files, f"Missing {f}"

    def test_page_css_module(self, simple_spec):
        css = generate_page_css(simple_spec.pages[0])
        assert ".page" in css
        assert ".form" in css

    def test_global_css_valid(self):
        css = global_css()
        result = validate_text("style.css", css)
        assert result.ok, f"Global CSS has issues: {result.issues}"


# ---------------------------------------------------------------------------
# Project export tests
# ---------------------------------------------------------------------------

class TestProjectExport:

    def test_render_package_json(self, simple_spec):
        plan = make_plan(simple_spec)
        pf = next(f for f in plan.files if f.relative_path == "package.json")
        content = render_file(pf, plan)
        assert content is not None
        import json
        data = json.loads(content)
        assert data["name"] == "testapp"
        assert "react" in data["dependencies"]

    def test_render_index_html(self, simple_spec):
        plan = make_plan(simple_spec)
        pf = next(f for f in plan.files if f.relative_path == "index.html")
        content = render_file(pf, plan)
        assert content is not None
        assert "TestApp" in content
        assert '<div id="root">' in content

    def test_render_page(self, simple_spec):
        plan = make_plan(simple_spec)
        pf = next(f for f in plan.files if f.relative_path == "src/pages/Home.tsx")
        content = render_file(pf, plan)
        assert content is not None
        assert "React" in content

    def test_render_readme(self, simple_spec):
        plan = make_plan(simple_spec)
        pf = next(f for f in plan.files if f.relative_path == "README.md")
        content = render_file(pf, plan)
        assert content is not None
        assert "TestApp" in content
        assert "npm install" in content

    def test_all_files_render(self, simple_spec):
        plan = make_plan(simple_spec)
        for pf in plan.files:
            content = render_file(pf, plan)
            # All files should produce non-empty content
            assert content is not None and len(content) > 10, \
                f"Empty content for {pf.relative_path}"


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidation:

    def test_valid_python(self):
        code = "x = 1 + 2\nprint(x)\n"
        result = validate_text("test.py", code)
        assert result.ok

    def test_invalid_python_syntax(self):
        code = "def foo(\n    x =\n"
        result = validate_text("test.py", code)
        assert not result.ok
        assert any("SyntaxError" in i.message for i in result.issues)

    def test_valid_json(self):
        result = validate_text("pkg.json", '{"name": "test", "version": "1.0.0"}')
        assert result.ok

    def test_invalid_json(self):
        result = validate_text("pkg.json", '{"name": "test"  "version": "1.0.0"}')
        assert not result.ok

    def test_balanced_typescript(self):
        code = "const x = () => { return 1; };\n"
        result = validate_text("app.ts", code)
        assert result.ok

    def test_unbalanced_css_braces(self):
        code = ".foo { color: red;\n"  # missing closing brace
        result = validate_text("style.css", code)
        assert not result.ok

    def test_bundle_validation(self, simple_spec):
        plan = make_plan(simple_spec)
        bundle = {pf.relative_path: render_file(pf, plan) for pf in plan.files}
        bundle = {k: v for k, v in bundle.items() if v}
        results = validate_bundle(bundle)
        errors = {k: v for k, v in results.items() if not v.ok}
        # Package.json and CSS files should be valid
        assert "package.json" not in errors, f"package.json invalid: {results['package.json'].issues}"


# ---------------------------------------------------------------------------
# Backend generation tests
# ---------------------------------------------------------------------------

class TestBackendGeneration:

    def test_schema_sql(self, multi_page_spec):
        sql = generate_schema_sql(multi_page_spec)
        assert "CREATE TABLE IF NOT EXISTS user" in sql
        assert "email TEXT" in sql
        assert "PRAGMA foreign_keys" in sql

    def test_models_py(self, multi_page_spec):
        code = generate_models_py(multi_page_spec)
        # Should be valid Python
        result = validate_text("models.py", code)
        assert result.ok, f"models.py invalid: {result.issues}"
        assert "@dataclass" in code
        assert "class User:" in code

    def test_database_py(self, multi_page_spec):
        code = generate_database_py(multi_page_spec)
        result = validate_text("database.py", code)
        assert result.ok, f"database.py invalid: {result.issues}"
        assert "connect" in code
        assert "PRAGMA" in code

    def test_logic_py(self, multi_page_spec):
        code = generate_logic_py(multi_page_spec)
        result = validate_text("logic.py", code)
        assert result.ok, f"logic.py invalid: {result.issues}"
        assert "create_user" in code
        assert "get_user" in code
        assert "list_user" in code
        assert "delete_user" in code
