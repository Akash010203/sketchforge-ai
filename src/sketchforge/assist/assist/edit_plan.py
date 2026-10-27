"""The typed edit plan: the only thing a planner (local or model) may produce.

A plan is data, not code: a short list of allowlisted operations that refer to components by id.
``validate_plan`` rejects anything unknown, out of range, locked or not editable *before* a command
exists; ``PlanCommand`` then applies the operations one by one against the live document and undoes
them as a single step. Planner output is never trusted, never "repaired" silently.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sketchforge.design_ir.schema import BBox, ComponentType, DesignDocument
from sketchforge.editor.design_commands import Command, MoveCommand, SetBBoxCommand, SetStyleCommand
from sketchforge.editor.property_editing import make_edit, parse_color
from sketchforge.exceptions import EditError, SketchForgeError

MAX_OPS = 8
TEXT_TYPES = {ComponentType.TEXT, ComponentType.HEADING, ComponentType.BUTTON, ComponentType.INPUT}
LIMIT_PX = 3000.0

COLOR_NAMES: dict[str, str] = {
    "red": "#dc2626", "orange": "#ea580c", "yellow": "#eab308", "green": "#16a34a", "teal": "#0d9488",
    "blue": "#2563eb", "navy": "#1e3a8a", "purple": "#7c3aed", "violet": "#7c3aed", "pink": "#db2777",
    "brown": "#92400e", "black": "#111827", "white": "#ffffff", "gray": "#6b7280", "grey": "#6b7280",
    "light gray": "#e5e7eb", "light grey": "#e5e7eb", "dark gray": "#374151", "dark grey": "#374151",
    "light blue": "#bfdbfe", "dark blue": "#1e40af", "light green": "#bbf7d0", "dark green": "#166534",
    "transparent": "transparent",
}


class InvalidPlan(SketchForgeError):
    """A plan failed validation. ``problems`` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems[:4]) + (f" (+{len(problems) - 4} more)" if len(problems) > 4 else ""))
        self.problems = problems


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class SetText(_Op):
    op: Literal["set_text"]
    text: str = Field(max_length=200)


class SetFill(_Op):
    op: Literal["set_fill"]
    color: str


class SetTextColor(_Op):
    op: Literal["set_text_color"]
    color: str


class SetBorder(_Op):
    op: Literal["set_border"]
    color: str


class Move(_Op):
    op: Literal["move"]
    dx: float = Field(0.0, ge=-LIMIT_PX, le=LIMIT_PX)
    dy: float = Field(0.0, ge=-LIMIT_PX, le=LIMIT_PX)


class SetPosition(_Op):
    op: Literal["set_position"]
    x: float | None = Field(None, ge=-LIMIT_PX, le=LIMIT_PX)
    y: float | None = Field(None, ge=-LIMIT_PX, le=LIMIT_PX)


class Resize(_Op):
    op: Literal["resize"]
    width: float | None = Field(None, gt=0, le=LIMIT_PX)
    height: float | None = Field(None, gt=0, le=LIMIT_PX)


class Grow(_Op):
    op: Literal["grow"]
    dw: float = Field(0.0, ge=-LIMIT_PX, le=LIMIT_PX)
    dh: float = Field(0.0, ge=-LIMIT_PX, le=LIMIT_PX)


class SetFontSize(_Op):
    op: Literal["set_font_size"]
    size: float = Field(ge=6, le=200)


class SetCornerRadius(_Op):
    op: Literal["set_corner_radius"]
    radius: float = Field(ge=0, le=500)


EditOp = Annotated[
    SetText | SetFill | SetTextColor | SetBorder | Move | SetPosition | Resize | Grow | SetFontSize | SetCornerRadius,
    Field(discriminator="op"),
]
OP_NAMES = ("set_text", "set_fill", "set_text_color", "set_border", "move", "set_position", "resize", "grow",
            "set_font_size", "set_corner_radius")


class EditPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ops: list[EditOp] = Field(min_length=1, max_length=MAX_OPS)
    explanation: str = Field("", max_length=400)

    @field_validator("explanation", mode="before")
    @classmethod
    def _coerce_none(cls, value: Any) -> Any:
        return "" if value is None else value


def resolve_color(value: str) -> str:
    """A colour name from :data:`COLOR_NAMES` or a hex string -> canonical ``#rrggbb``/keyword."""
    name = " ".join(str(value).lower().replace("-", " ").split())
    return parse_color(COLOR_NAMES.get(name, name))


def parse_plan(data: Any) -> EditPlan:
    """Validate raw (already JSON-decoded) planner output. Raises :class:`InvalidPlan`."""
    try:
        return EditPlan.model_validate(data)
    except ValidationError as exc:
        problems = []
        for err in exc.errors()[:6]:
            loc = ".".join(str(p) for p in err["loc"])
            problems.append(f"{loc}: {err['msg']}")
        raise InvalidPlan(problems) from exc


def validate_plan(plan: EditPlan, doc: DesignDocument) -> None:
    """Check every operation against the document. Raises :class:`InvalidPlan` listing all problems."""
    problems: list[str] = []
    for i, op in enumerate(plan.ops, 1):
        tag = f"op {i} ({op.op} on {op.target})"
        comp = doc.get(op.target)
        if comp is None:
            problems.append(f"{tag}: no such component")
            continue
        if comp.id == doc.root_id:
            problems.append(f"{tag}: the page itself cannot be edited this way")
            continue
        if comp.locked:
            problems.append(f"{tag}: component is locked")
        field = {"set_text": "text", "set_fill": "style", "set_border": "style", "set_corner_radius": "style",
                 "set_text_color": "typography", "set_font_size": "typography"}.get(op.op, "bbox")
        if field not in comp.editable:
            problems.append(f"{tag}: '{field}' is not editable on this component")
        if op.op == "set_text" and comp.type not in TEXT_TYPES | {ComponentType.CHECKBOX, ComponentType.RADIO}:
            problems.append(f"{tag}: a {comp.type.value} does not carry text")
        if op.op in ("set_text_color", "set_font_size") and comp.typography is None:
            problems.append(f"{tag}: a {comp.type.value} has no text styling")
        if op.op in ("set_fill", "set_text_color", "set_border"):
            try:
                resolve_color(op.color)
            except EditError as exc:
                problems.append(f"{tag}: {exc}")
        if op.op in ("resize", "set_position") and op.model_dump().get(
                "width" if op.op == "resize" else "x") is None and op.model_dump().get(
                "height" if op.op == "resize" else "y") is None:
            problems.append(f"{tag}: nothing to change")
    if problems:
        raise InvalidPlan(problems)


def _command_for(op: Any, doc: DesignDocument) -> list[Command]:
    comp = doc.require(op.target)
    b = comp.bbox
    kind = op.op
    if kind == "set_text":
        return [make_edit(doc, comp.id, "text", op.text)]
    if kind == "set_fill":
        return [make_edit(doc, comp.id, "fill", resolve_color(op.color))]
    if kind == "set_text_color":
        return [make_edit(doc, comp.id, "color", resolve_color(op.color))]
    if kind == "set_border":
        cmds: list[Command] = [make_edit(doc, comp.id, "stroke", resolve_color(op.color))]
        if comp.style.stroke_width == 0:
            cmds.append(SetStyleCommand(comp.id, stroke_width=1.0))
        return cmds
    if kind == "move":
        return [MoveCommand(comp.id, op.dx, op.dy)]
    if kind == "set_position":
        return [MoveCommand(comp.id, (op.x - b.x) if op.x is not None else 0.0,
                            (op.y - b.y) if op.y is not None else 0.0)]
    if kind == "resize":
        return [SetBBoxCommand(comp.id, BBox(x=b.x, y=b.y, w=op.width or b.w, h=op.height or b.h))]
    if kind == "grow":
        w, h = b.w + op.dw, b.h + op.dh
        if w <= 0 or h <= 0:
            raise EditError(f"{comp.id} would have no size left after shrinking")
        return [SetBBoxCommand(comp.id, BBox(x=b.x, y=b.y, w=w, h=h))]
    if kind == "set_font_size":
        return [make_edit(doc, comp.id, "font_size", op.size)]
    if kind == "set_corner_radius":
        return [make_edit(doc, comp.id, "corner_radius", op.radius)]
    raise EditError(f"unknown operation {kind!r}")


class PlanCommand(Command):
    """Apply a validated plan as one undoable step.

    Operations are resolved against the live document one at a time, so a ``move`` followed by a
    ``resize`` of the same component compose correctly. If any operation fails, the ones already
    applied are undone and the document is left exactly as it was.
    """

    def __init__(self, plan: EditPlan, description: str | None = None) -> None:
        self.plan = plan
        self.description = description or f"edit plan: {', '.join(o.op for o in plan.ops)}"
        self._applied: list[Command] = []

    def do(self, doc: DesignDocument) -> None:
        self._applied = []
        try:
            for op in self.plan.ops:
                for cmd in _command_for(op, doc):
                    cmd.respect_locks = self.respect_locks
                    cmd.do(doc)
                    self._applied.append(cmd)
        except Exception:
            for cmd in reversed(self._applied):
                cmd.undo(doc)
            self._applied = []
            raise

    def undo(self, doc: DesignDocument) -> None:
        for cmd in reversed(self._applied):
            cmd.undo(doc)

    def touched_ids(self) -> set[str]:
        return {op.target for op in self.plan.ops}
