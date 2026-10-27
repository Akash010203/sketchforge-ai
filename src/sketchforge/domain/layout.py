"""Container layout settings and shared container type set."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from sketchforge.domain.base import StrictModel
from sketchforge.domain.component_types import ComponentType

CONTAINER_TYPES = frozenset(
    {
        ComponentType.PAGE,
        ComponentType.CONTAINER,
        ComponentType.HEADER,
        ComponentType.SIDEBAR,
        ComponentType.FOOTER,
        ComponentType.CARD,
    }
)


class LayoutSpec(StrictModel):
    """How a container arranges its children. Geometry stays authoritative; this is a constraint
    and a code-generation hint. ``inferred`` marks values guessed from the sketch."""

    mode: Literal["absolute", "flex", "grid"] = "absolute"
    direction: Literal["row", "column"] = "column"
    gap: float = Field(0.0, ge=0.0)
    padding: float = Field(0.0, ge=0.0)
    align_items: Literal["start", "center", "end", "stretch"] = "start"
    justify_content: Literal["start", "center", "end", "space-between"] = "start"
    columns: int | None = Field(None, ge=1)
    inferred: bool = False
