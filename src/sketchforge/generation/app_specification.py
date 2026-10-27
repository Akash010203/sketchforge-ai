"""Application specification: the structured contract between the Design IR and code generation.

The AppSpec describes what the generated application should do — not how the code is written.
It is produced by analysing the Design IR and any user-supplied requirements.
It is the source of truth for all generation phases (frontend, backend, tests).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldSpec:
    """One input field in a form."""
    name: str                       # e.g. "email"
    label: str                      # human-readable
    type: str = "text"              # "text" | "email" | "password" | "number" | "select"
    required: bool = True
    placeholder: str = ""
    validation: list[str] = field(default_factory=list)  # e.g. ["email", "max_length:255"]
    options: list[str] = field(default_factory=list)      # for "select" type


@dataclass
class ActionSpec:
    """One user action (button, link, nav item)."""
    label: str
    action: str    # "navigate" | "submit_form" | "toggle" | "open_modal"
    target: str = ""  # page name, modal id, or URL fragment


@dataclass
class PageSpec:
    """One page or view in the generated application."""
    name: str                       # e.g. "login"
    title: str                      # e.g. "Sign In"
    route: str                      # e.g. "/login"
    description: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)  # component ir snapshots
    forms: list[list[FieldSpec]] = field(default_factory=list)
    actions: list[ActionSpec] = field(default_factory=list)
    is_authenticated: bool = False  # whether access requires login


@dataclass
class EntitySpec:
    """One data entity for the backend."""
    name: str                       # e.g. "User"
    fields: list[FieldSpec] = field(default_factory=list)
    primary_key: str = "id"
    timestamps: bool = True


@dataclass
class AppSpec:
    """Top-level application specification derived from one or more Design IR documents."""
    name: str
    description: str = ""
    pages: list[PageSpec] = field(default_factory=list)
    entities: list[EntitySpec] = field(default_factory=list)
    requires_auth: bool = False
    tech_frontend: str = "react-ts"  # "react-ts" | "html-css-js"
    tech_backend: str = "none"       # "none" | "python-sqlite" (legacy enabled flag)
    database: str = "sqlite"          # sqlite | postgresql | mysql
    orm: str = "dataclass"            # dataclass | sqlalchemy | prisma (Prisma schema/client)
    api_target: str = "flask"         # flask | fastapi | graphql (Python targets)
    migrations: bool = False
    authentication: bool = False      # session/password/JWT/OAuth scaffolding
    acceptance_criteria: list[str] = field(default_factory=list)

    def page_by_name(self, name: str) -> PageSpec | None:
        return next((p for p in self.pages if p.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)


def spec_from_document(doc: "Any", app_name: str = "GeneratedApp") -> AppSpec:
    """Derive a minimal AppSpec from a single DesignDocument.

    This is a heuristic pass:
    - Each page-root becomes an AppSpec page.
    - INPUT components become form fields.
    - BUTTON components become actions.
    - The resulting spec is marked up for the user to refine before generation.
    """
    from sketchforge.design_ir.schema import ComponentType, DesignDocument

    assert isinstance(doc, DesignDocument)
    pages: list[PageSpec] = []
    root = doc.root

    # Build one page for the single imported document
    inputs = [c for c in doc.components if c.type is ComponentType.INPUT]
    buttons = [c for c in doc.components if c.type is ComponentType.BUTTON]

    fields = [
        FieldSpec(
            name=f"field_{i}",
            label=c.text or f"Field {i + 1}",
            placeholder=c.text or "",
        )
        for i, c in enumerate(inputs)
    ]
    actions = [
        ActionSpec(label=c.text or f"Action {i + 1}", action="submit_form" if inputs else "navigate")
        for i, c in enumerate(buttons)
    ]
    page = PageSpec(
        name=doc.name.lower().replace(" ", "_"),
        title=doc.name,
        route="/",
        description=f"Page generated from sketch '{doc.name}'",
        forms=[fields] if fields else [],
        actions=actions,
    )
    pages.append(page)

    # Detect if there are enough fields to suggest a backend
    requires_backend = len(inputs) >= 2 and len(buttons) >= 1
    entities = []
    if requires_backend:
        entity_fields = [FieldSpec(name=f.name, label=f.label, type="text") for f in fields]
        entities.append(EntitySpec(name="Record", fields=entity_fields))

    return AppSpec(
        name=app_name,
        description=f"Application generated from sketch '{doc.name}'",
        pages=pages,
        entities=entities,
        requires_auth=any(
            "login" in (c.text or "").lower() or "password" in (c.text or "").lower()
            for c in doc.components
        ),
        tech_frontend="react-ts",
        tech_backend="python-sqlite" if requires_backend else "none",
        acceptance_criteria=[
            f"Page '{page.title}' renders without errors",
            "All form fields are present and labelled",
            "Buttons trigger the expected action",
        ],
    )
