"""Component entities and their visual value objects."""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from sketchforge.constants import DEFAULT_FONT_FAMILY
from sketchforge.domain.base import StrictModel
from sketchforge.domain.interaction import Interaction
from sketchforge.domain.layout import LayoutSpec
from sketchforge.domain.component_types import ComponentType

ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
_HEX_RE = re.compile(r"^#(?:[0-9a-f]{6}|[0-9a-f]{8})$")

_ID_RE = re.compile(ID_PATTERN)


def _check_color(value: str) -> str:
    text = value.strip().lower()
    if text in {"transparent", "none"} or _HEX_RE.match(text):
        return text
    raise ValueError(f"invalid color {value!r}: use #rrggbb, #rrggbbaa, 'transparent' or 'none'")

HexColor = Annotated[str, AfterValidator(_check_color)]


class BBox(BaseModel):
    """Axis-aligned box. Immutable: edits replace the whole box so every change is recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float
    y: float
    w: float
    h: float

    @field_validator("x", "y", "w", "h")
    @classmethod
    def _finite_and_rounded(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinates must be finite numbers")
        return round(value, 3)

    @model_validator(mode="after")
    def _positive_size(self) -> BBox:
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"width and height must be > 0 (got w={self.w}, h={self.h})")
        return self

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h

class Typography(StrictModel):
    font_family: str = DEFAULT_FONT_FAMILY
    font_size: float = Field(16.0, ge=6.0, le=200.0)
    font_weight: int = Field(400, ge=100, le=900)
    line_height: float = Field(1.3, ge=0.8, le=3.0)
    text_align: Literal["left", "center", "right"] = "left"
    color: HexColor = "#111827"

class Style(StrictModel):
    fill: HexColor = "transparent"
    stroke: HexColor = "none"
    stroke_width: float = Field(0.0, ge=0.0, le=32.0)
    corner_radius: float = Field(0.0, ge=0.0, le=500.0)
    opacity: float = Field(1.0, ge=0.0, le=1.0)

class DetectionInfo(StrictModel):
    """Provenance and uncertainty for a component that came from an image."""

    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source: Literal["heuristic", "model", "user", "synthetic", "remote"] = "heuristic"
    source_bbox: BBox | None = None  # box in original-image pixels
    type_scores: dict[str, float] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    ambiguous: bool = False

class CodeMapping(StrictModel):
    """Where this component lands in generated code (filled in by the generation phase)."""

    component_name: str | None = None
    file_path: str | None = None

class Component(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: ComponentType
    name: str | None = Field(None, max_length=120)
    parent_id: str | None = Field(None, pattern=ID_PATTERN)
    bbox: BBox
    z_index: int = 0
    text: str | None = Field(None, max_length=2000)
    text_is_inferred: bool = False
    typography: Typography | None = None
    style: Style = Field(default_factory=Style)
    layout: LayoutSpec | None = None
    detection: DetectionInfo | None = None
    states: list[str] = Field(default_factory=lambda: ["default"])
    interactions: list[Interaction] = Field(default_factory=list)
    visible: bool = True
    locked: bool = False
    editable: list[str] = Field(default_factory=lambda: ["text", "bbox", "style", "typography"])
    codegen: CodeMapping | None = None

def is_valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value))
