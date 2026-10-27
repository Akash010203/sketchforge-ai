"""Deterministic error injection, so a repair can be demonstrated and tested reproducibly.

Each injection applies one ordinary edit command (so it is undoable and logged) that causes
exactly one kind of measurable issue, and returns a record of what it did and which issue code the
evaluator is expected to report.
"""

from __future__ import annotations

from dataclasses import dataclass

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.schema import BBox, Component, ComponentType, DesignDocument
from sketchforge.editor.design_commands import (
    Command,
    MoveCommand,
    SetBBoxCommand,
    SetStyleCommand,
    SetTextCommand,
)
from sketchforge.editor.undo_redo import UndoStack
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.exceptions import RepairError
from sketchforge.layout.grouping import alignable_siblings, repeated_groups

KINDS = ("overflow", "misalignment", "spacing", "text_overflow", "low_contrast", "small_control", "overlap")


@dataclass(frozen=True)
class Injection:
    kind: str
    component_ids: tuple[str, ...]
    description: str
    expected_code: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "components": list(self.component_ids),
                "description": self.description, "expected_issue": self.expected_code}


def _containers(doc: DesignDocument) -> list[Component]:
    from sketchforge.design_ir.schema import CONTAINER_TYPES

    return [c for c in preorder(doc) if c.type in CONTAINER_TYPES and c.id != doc.root_id]


def _pick_overflow(doc: DesignDocument) -> tuple[Command, Injection]:
    # prefer a control inside a container; fall back to one placed directly on the page
    for parent in _containers(doc) + [doc.root]:
        for comp in alignable_siblings(doc, parent.id):
            if comp.type in (ComponentType.BUTTON, ComponentType.INPUT):
                dx = (parent.bbox.x2 - comp.bbox.x2) + 30.0
                page_level = parent.id == doc.root_id
                return (
                    MoveCommand(comp.id, dx, 0.0, reason=f"INJECTED: push {comp.id} {dx:.0f}px right"),
                    Injection("overflow", (comp.id,),
                              f"moved {comp.id} so it pokes 30px out of {'the page' if page_level else parent.id}",
                              I.OVERFLOW_PAGE if page_level else I.OVERFLOW_PARENT),
                )
    raise RepairError("no button or input to push out")


def _pick_misalignment(doc: DesignDocument, tol: float) -> tuple[Command, Injection]:
    for parent in _containers(doc) + [doc.root]:
        kids = alignable_siblings(doc, parent.id)
        for comp in kids:
            partners = [o for o in kids if o.id != comp.id and abs(o.bbox.x - comp.bbox.x) <= tol
                        and o.bbox.y != comp.bbox.y]
            if partners and comp.type in (ComponentType.INPUT, ComponentType.BUTTON, ComponentType.TEXT):
                return (
                    MoveCommand(comp.id, 9.0, 0.0, reason=f"INJECTED: nudge {comp.id} 9px right"),
                    Injection("misalignment", (comp.id,), f"shifted {comp.id} 9px off its group's left edge",
                              I.MISALIGNED),
                )
    raise RepairError("no aligned siblings to disturb")


def _pick_spacing(doc: DesignDocument) -> tuple[Command, Injection]:
    best = None
    for parent in _containers(doc) + [doc.root]:
        for g in repeated_groups(doc, parent.id):
            if best is None or len(g.member_ids) > len(best.member_ids):
                best = g
    if best is None:
        raise RepairError("no repeated group of 3+ similar items")
    victim = best.member_ids[len(best.member_ids) // 2]
    dx, dy = (0.0, 12.0) if best.axis == "column" else (12.0, 0.0)
    return (
        MoveCommand(victim, dx, dy, reason=f"INJECTED: nudge {victim} 12px along its group"),
        Injection("spacing", (victim,), f"shifted {victim} 12px so its group's pitch is uneven",
                  I.UNEVEN_SPACING),
    )


def _pick_text(doc: DesignDocument, min_font_px: float = 10.0) -> tuple[Command, Injection]:
    """Lengthen a label until it overflows its box.

    The overflow is sized so that shrinking the font to ``min_font_px`` *could* fix it: an
    injected fault that no strategy could ever repair would test the fixture, not the engine.
    """
    from sketchforge.domain.typography import estimate_text_width
    from sketchforge.evaluation.text_metrics import horizontal_padding

    for comp in doc.components:
        if comp.type in (ComponentType.BUTTON, ComponentType.INPUT) and comp.text and comp.typography:
            t = comp.typography
            avail = comp.bbox.w - 2 * horizontal_padding(comp.type)

            def width(text: str, t=t) -> float:
                return estimate_text_width(text, t.font_size, t.font_weight)

            fixable_ratio = 0.92 * t.font_size / min_font_px  # largest overflow a font shrink can absorb
            want, ceiling = 1.10, max(fixable_ratio, 1.03)
            long_text = comp.text
            while width(long_text) < want * avail and width(long_text + " ab") <= ceiling * avail:
                long_text += " ab"
            while width(long_text) <= 1.02 * avail:  # must overflow, even if no font shrink can fix it
                long_text += " ab"
            return (
                SetTextCommand(comp.id, long_text, mark_inferred=True),
                Injection("text_overflow", (comp.id,), f"replaced the text of {comp.id} with a long label",
                          I.TEXT_OVERFLOW),
            )
    raise RepairError("no button or input with text")


def _pick_contrast(doc: DesignDocument) -> tuple[Command, Injection]:
    for comp in doc.components:
        if comp.type is ComponentType.BUTTON and comp.typography:
            return (
                SetStyleCommand(comp.id, fill="#dbeafe"),
                Injection("low_contrast", (comp.id,), f"gave {comp.id} a pale fill under its white label",
                          I.LOW_CONTRAST),
            )
    raise RepairError("no button to recolour")


def _pick_small(doc: DesignDocument) -> tuple[Command, Injection]:
    for comp in doc.components:
        if comp.type in (ComponentType.BUTTON, ComponentType.INPUT):
            b = comp.bbox
            return (
                SetBBoxCommand(comp.id, BBox(x=b.x, y=b.cy - 9, w=b.w, h=18), reason="INJECTED: shrink height"),
                Injection("small_control", (comp.id,), f"squashed {comp.id} to 18px tall", I.TOUCH_TARGET_SMALL),
            )
    raise RepairError("no control to shrink")


def _pick_overlap(doc: DesignDocument) -> tuple[Command, Injection]:
    for parent in _containers(doc) + [doc.root]:
        kids = sorted(alignable_siblings(doc, parent.id), key=lambda c: (c.bbox.y, c.bbox.x))
        for upper, lower in zip(kids, kids[1:], strict=False):
            if lower.bbox.y >= upper.bbox.y2 and abs(lower.bbox.x - upper.bbox.x) < 0.5 * upper.bbox.w:
                dy = -(lower.bbox.y - upper.bbox.y2) - 0.4 * min(upper.bbox.h, lower.bbox.h)
                return (
                    MoveCommand(lower.id, 0.0, dy, reason=f"INJECTED: pull {lower.id} up into {upper.id}"),
                    Injection("overlap", (upper.id, lower.id), f"pulled {lower.id} up so it overlaps {upper.id}",
                              I.OVERLAP),
                )
    raise RepairError("no vertically stacked siblings to overlap")


def inject(
    doc: DesignDocument,
    kind: str,
    stack: UndoStack | None = None,
    constraints: LayoutConstraints | None = None,
) -> Injection:
    """Apply one injection (through ``stack`` when given, so it can be undone)."""
    c = constraints or LayoutConstraints()
    builders = {
        "overflow": lambda: _pick_overflow(doc),
        "misalignment": lambda: _pick_misalignment(doc, c.align_tolerance_px),
        "spacing": lambda: _pick_spacing(doc),
        "text_overflow": lambda: _pick_text(doc, c.min_font_size_px),
        "low_contrast": lambda: _pick_contrast(doc),
        "small_control": lambda: _pick_small(doc),
        "overlap": lambda: _pick_overlap(doc),
    }
    if kind not in builders:
        raise RepairError(f"unknown injection kind {kind!r}; choose from {', '.join(KINDS)}")
    command, record = builders[kind]()
    command.respect_locks = False  # the injection is a test fixture, not a user edit
    if stack is not None:
        stack.execute(command)
    else:
        command.do(doc)
    return record
