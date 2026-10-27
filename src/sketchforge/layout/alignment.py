"""Alignment moves: minimal translations that make near-aligned siblings exactly aligned."""

from __future__ import annotations

from dataclasses import dataclass

from sketchforge.design_ir.document import move_subtree, preorder
from sketchforge.design_ir.schema import CONTAINER_TYPES, DesignDocument
from sketchforge.layout.grouping import Misalignment, find_misalignments, shift_to_edge


@dataclass(frozen=True)
class Move:
    component_id: str
    dx: float
    dy: float
    reason: str


def alignment_moves(doc: DesignDocument, radius: float, tolerance: float) -> list[Move]:
    moves: list[Move] = []
    for comp in preorder(doc):
        if comp.type not in CONTAINER_TYPES:
            continue
        for m in find_misalignments(doc, comp.id, radius, tolerance):
            moves.append(move_for(doc, m))
    return moves


def move_for(doc: DesignDocument, m: Misalignment) -> Move:
    box = doc.require(m.component_id).bbox
    dx, dy = shift_to_edge(box, m.edge, m.target)
    return Move(
        m.component_id, round(dx, 3), round(dy, 3),
        f"{m.edge} edge is {m.residual:.1f}px from {', '.join(m.partners)}",
    )


def apply_alignment(doc: DesignDocument, radius: float, tolerance: float, max_passes: int = 3) -> int:
    """Snap near-aligned siblings in place (used while building a document from a sketch)."""
    total = 0
    for _ in range(max_passes):
        moves = alignment_moves(doc, radius, tolerance)
        applied = 0
        touched: set[str] = set()
        for mv in moves:
            if mv.component_id in touched:
                continue
            touched.add(mv.component_id)
            move_subtree(doc, mv.component_id, mv.dx, mv.dy)
            applied += 1
        total += applied
        if applied == 0:
            break
    return total
