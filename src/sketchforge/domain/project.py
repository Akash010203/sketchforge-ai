"""Project, page, and document metadata entities."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, PrivateAttr, model_validator

from sketchforge.constants import PIPELINE_VERSION, SCHEMA_VERSION
from sketchforge.domain.base import StrictModel
from sketchforge.domain.component import Component, ID_PATTERN, HexColor

class Viewport(StrictModel):
    width: int = Field(1024, ge=1, le=20000)
    height: int = Field(768, ge=1, le=20000)
    device: Literal["desktop", "tablet", "mobile", "custom"] = "desktop"

class Page(StrictModel):
    width: float = Field(gt=0, le=20000)
    height: float = Field(gt=0, le=20000)
    background: HexColor = "#ffffff"
    viewport: Viewport = Field(default_factory=Viewport)

class SourceTransform(StrictModel):
    """Maps original-image pixels to design pixels: ``design = (source - offset) * scale``."""

    scale: float = Field(gt=0)
    offset_x: float = 0.0
    offset_y: float = 0.0

class DocumentMetadata(StrictModel):
    source_image_sha256: str | None = None
    source_size: tuple[int, int] | None = None  # (width, height) of the original image
    source_transform: SourceTransform | None = None
    pipeline_version: str = PIPELINE_VERSION
    notes: list[str] = Field(default_factory=list)

class DesignDocument(StrictModel):
    schema_version: str = SCHEMA_VERSION
    document_id: str = Field(pattern=ID_PATTERN)
    name: str = Field("Untitled design", max_length=200)
    page: Page
    root_id: str = Field(pattern=ID_PATTERN)
    components: list[Component]
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)

    _index: dict[str, Component] | None = PrivateAttr(default=None)
    _children: dict[str, list[str]] | None = PrivateAttr(default=None)

    # ------------------------------------------------------------------ equality & index
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DesignDocument):
            return NotImplemented
        return self.model_dump() == other.model_dump()

    __hash__ = None  # type: ignore[assignment]

    def invalidate_index(self) -> None:
        """Call after any structural change (add/remove/reparent/replace components)."""
        self._index = None
        self._children = None

    def _ensure_index(self) -> None:
        if self._index is not None and len(self._index) == len(self.components):
            return
        index: dict[str, Component] = {}
        for comp in self.components:
            index[comp.id] = comp
        children: dict[str, list[tuple[int, int, str]]] = {}
        for order, comp in enumerate(self.components):
            if comp.parent_id is not None:
                children.setdefault(comp.parent_id, []).append((comp.z_index, order, comp.id))
        self._index = index
        self._children = {pid: [cid for _, _, cid in sorted(items)] for pid, items in children.items()}

    # ------------------------------------------------------------------ accessors
    def get(self, component_id: str) -> Component | None:
        self._ensure_index()
        assert self._index is not None
        return self._index.get(component_id)

    def require(self, component_id: str) -> Component:
        comp = self.get(component_id)
        if comp is None:
            raise KeyError(f"no component with id {component_id!r}")
        return comp

    def children_ids(self, component_id: str) -> list[str]:
        self._ensure_index()
        assert self._children is not None
        return list(self._children.get(component_id, []))

    def children_of(self, component_id: str) -> list[Component]:
        return [self.require(cid) for cid in self.children_ids(component_id)]

    @property
    def root(self) -> Component:
        return self.require(self.root_id)

    def snapshot(self) -> dict[str, Any]:
        """Plain-data copy for undo/rollback. Restore with :meth:`restore`."""
        return self.model_dump(mode="python")

    def restore(self, snapshot: dict[str, Any]) -> None:
        restored = DesignDocument.model_validate(snapshot)
        self.schema_version = restored.schema_version
        self.name = restored.name
        self.page = restored.page
        self.root_id = restored.root_id
        self.components = restored.components
        self.metadata = restored.metadata
        self.invalidate_index()


class PageRoute(StrictModel):
    """A URL route pointing to one page document in a multi-page project."""

    page_id: str = Field(pattern=ID_PATTERN)
    path: str = Field(pattern=r"^/(?:[A-Za-z0-9_~.-]+(?:/[A-Za-z0-9_~.-]+)*)?$")
    title: str | None = Field(default=None, max_length=200)
    requires_auth: bool = False


class DesignProject(StrictModel):
    """A routable application composed of independent single-page Design IR documents.

    Page documents remain independently editable and retain their existing hashes and
    serialization contract. ``routes`` maps their stable ``document_id`` values to URL paths.
    """

    schema_version: str = SCHEMA_VERSION
    project_id: str = Field(pattern=ID_PATTERN)
    name: str = Field("Untitled project", max_length=200)
    pages: list[DesignDocument] = Field(min_length=1)
    routes: list[PageRoute] = Field(min_length=1)
    start_page_id: str = Field(pattern=ID_PATTERN)

    @model_validator(mode="after")
    def validate_routing(self) -> "DesignProject":
        page_ids = [page.document_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("page document_id values must be unique within a project")
        route_ids = [route.page_id for route in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("each page may have only one route")
        if len({route.path.casefold() for route in self.routes}) != len(self.routes):
            raise ValueError("route paths must be unique (case-insensitive)")
        unknown = set(route_ids) - set(page_ids)
        if unknown:
            raise ValueError(f"routes reference unknown page ids: {sorted(unknown)}")
        missing = set(page_ids) - set(route_ids)
        if missing:
            raise ValueError(f"pages are missing routes: {sorted(missing)}")
        if self.start_page_id not in set(page_ids):
            raise ValueError("start_page_id must reference a project page")
        return self

    def page_by_id(self, page_id: str) -> DesignDocument | None:
        return next((page for page in self.pages if page.document_id == page_id), None)

    def route_for(self, page_id: str) -> PageRoute | None:
        return next((route for route in self.routes if route.page_id == page_id), None)
