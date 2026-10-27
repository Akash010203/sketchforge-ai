"""Project planner: converts an AppSpec into a virtual project file tree.

This module does NOT write files to disk — it produces a structured plan that
``file_tree.py`` can then materialise.  Separation ensures the plan is
testable without side-effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sketchforge.generation.app_specification import AppSpec, PageSpec


@dataclass
class PlannedFile:
    """One file that will be generated."""
    relative_path: str          # POSIX, relative to the project root
    generator: str              # symbolic tag ("component", "page", "style", "test", etc.)
    context: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class ProjectPlan:
    """Complete blueprint for a generated application."""
    spec: AppSpec
    tech_frontend: str          # "react-ts" | "html-css-js"
    tech_backend: str           # "none" | "python-sqlite"
    files: list[PlannedFile] = field(default_factory=list)
    directory_roots: list[str] = field(default_factory=list)

    def add(
        self,
        path: str,
        generator: str,
        description: str = "",
        **ctx: Any,
    ) -> None:
        self.files.append(PlannedFile(path, generator, dict(ctx), description))

    def paths(self) -> list[str]:
        return [f.relative_path for f in self.files]

    def by_generator(self, tag: str) -> list[PlannedFile]:
        return [f for f in self.files if f.generator == tag]


# ---------------------------------------------------------------------------
def plan_react_ts(spec: AppSpec) -> ProjectPlan:
    """Produce a full React + TypeScript project plan from an AppSpec."""
    plan = ProjectPlan(
        spec=spec,
        tech_frontend="react-ts",
        tech_backend=spec.tech_backend,
        directory_roots=[
            "src/components",
            "src/pages",
            "src/styles",
            "src/types",
            "public",
        ],
    )

    # ---- scaffold files -------------------------------------------------------
    plan.add("package.json",       "scaffold", description="npm package manifest")
    plan.add("tsconfig.json",      "scaffold", description="TypeScript compiler options")
    plan.add("vite.config.ts",     "scaffold", description="Vite build configuration")
    plan.add("index.html",         "scaffold", description="Vite entry HTML")
    plan.add("src/main.tsx",       "scaffold", description="React entry point")
    plan.add("src/App.tsx",        "scaffold", description="Root application component with routing")
    plan.add("src/styles/global.css", "style_global", description="Global CSS reset + design tokens")

    # ---- shared component types -----------------------------------------------
    plan.add(
        "src/types/design.ts",
        "types",
        description="Shared TypeScript interfaces derived from Design IR",
        components=[
            c.get("type", "unknown") if isinstance(c, dict) else getattr(c, "type", "unknown")
            for c in spec.pages[0].components
        ] if spec.pages else [],
    )

    # ---- per-page files -------------------------------------------------------
    for page in spec.pages:
        slug = page.name.replace(" ", "_").lower()
        plan.add(
            f"src/pages/{_pascal(slug)}.tsx",
            "page",
            description=f"Page component for {page.title}",
            page=page,
        )
        plan.add(
            f"src/styles/{slug}.module.css",
            "style_module",
            description=f"CSS module for {page.title}",
            page=page,
        )

    # ---- shared UI components (unique component types across all pages) ------
    seen: set[str] = set()
    for page in spec.pages:
        for comp in page.components:
            ctype = comp.get("type", "unknown")
            if ctype not in seen:
                seen.add(ctype)
                plan.add(
                    f"src/components/{_pascal(ctype)}.tsx",
                    "component",
                    description=f"Reusable {ctype} component",
                    component_type=ctype,
                )

    # ---- router ---------------------------------------------------------------
    plan.add("src/router.tsx", "scaffold", description="React Router v6 route tree", spec=spec)

    # ---- backend stub (if needed) -------------------------------------------
    if spec.tech_backend != "none":
        plan.directory_roots.extend(["backend", "backend/tests"])
        if spec.orm != "prisma":
            plan.add("backend/models.py",    "backend_models",    description="Generated data models")
            plan.add("backend/database.py",  "backend_db",        description="DB init and session management")
            plan.add("backend/logic.py",     "backend_logic",     description="Business logic and CRUD functions")
            plan.add("backend/schema.sql",   "backend_schema",    description="Raw SQL schema DDL")
        if spec.orm == "dataclass" and spec.database == "sqlite":
            plan.add("backend/tests/test_models.py", "backend_test", description="pytest model tests")
        if spec.orm != "prisma":
            plan.add("backend/api.py", "backend_api", description=f"{spec.api_target} API")
        if spec.orm == "prisma":
            plan.add("backend/prisma/schema.prisma", "backend_prisma", description="Prisma schema")
            plan.add("backend/package.json", "backend_prisma_package", description="Prisma client scripts and dependencies")
        if spec.orm != "prisma":
            plan.add("requirements.txt", "backend_requirements", description="Backend dependencies")
        if spec.authentication:
            plan.add("backend/auth.py", "backend_auth", description="Password and JWT helpers")
        if spec.migrations and spec.orm != "prisma":
            plan.directory_roots.append("migrations/versions")
            plan.add("alembic.ini", "backend_alembic_ini", description="Alembic configuration")
            plan.add("migrations/env.py", "backend_migration_env", description="Alembic migration environment")
            plan.add("migrations/script.py.mako", "backend_migration_template", description="Alembic revision template")

    # ---- README ---------------------------------------------------------------
    plan.add(
        "README.md",
        "readme",
        description="Setup, run, test instructions",
        spec=spec,
    )

    return plan


def plan_html_css(spec: AppSpec) -> ProjectPlan:
    """Produce a simple HTML/CSS/JS project plan."""
    plan = ProjectPlan(
        spec=spec,
        tech_frontend="html-css-js",
        tech_backend=spec.tech_backend,
        directory_roots=["css", "js"],
    )
    plan.add("css/style.css", "style_global", description="Global styles")
    for page in spec.pages:
        slug = page.name.replace(" ", "_").lower()
        plan.add(f"{slug}.html", "page_html", description=f"HTML page for {page.title}", page=page)
        plan.add(f"js/{slug}.js", "page_js", description=f"JS for {page.title}", page=page)
    plan.add("README.md", "readme", description="Setup instructions", spec=spec)
    return plan


def make_plan(spec: AppSpec) -> ProjectPlan:
    """Entry point: choose the right planner from the AppSpec."""
    if spec.database not in {"sqlite", "postgresql", "mysql"}:
        raise ValueError(f"Unsupported database: {spec.database}")
    if spec.orm not in {"dataclass", "sqlalchemy", "prisma"}:
        raise ValueError(f"Unsupported ORM: {spec.orm}")
    if spec.api_target not in {"flask", "fastapi", "graphql"}:
        raise ValueError(f"Unsupported API target: {spec.api_target}")
    from sketchforge.generation.backend.schema_generator import _check_identifier, _snake
    for entity in spec.entities:
        _check_identifier(entity.name)
        _check_identifier(entity.primary_key)
        _check_identifier(_snake(entity.name))
        for field_spec in entity.fields:
            _check_identifier(field_spec.name)
    if spec.orm == "prisma" and spec.migrations:
        # Prisma migrations are included in backend/package.json scripts.
        pass
    elif spec.migrations and spec.orm != "sqlalchemy" and spec.database == "sqlite":
        raise ValueError("Alembic migrations require orm='sqlalchemy'.")
    if spec.orm == "prisma" and spec.authentication:
        raise ValueError("Prisma authentication generation is not available; use orm='sqlalchemy' or 'dataclass'.")
    if spec.tech_frontend == "react-ts":
        return plan_react_ts(spec)
    return plan_html_css(spec)


# ---------------------------------------------------------------------------
def _pascal(s: str) -> str:
    """Convert snake_case or kebab-case to PascalCase."""
    return "".join(part.capitalize() for part in s.replace("-", "_").split("_"))
