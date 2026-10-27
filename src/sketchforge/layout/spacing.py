"""Spacing moves: make the pitch inside a repeated group uniform with minimal displacement."""

from __future__ import annotations

from sketchforge.design_ir.document import move_subtree, preorder
from sketchforge.design_ir.schema import CONTAINER_TYPES, DesignDocument
from sketchforge.layout.alignment import Move
from sketchforge.layout.grouping import RepeatedGroup, repeated_groups, robust_pitch_fit


def group_moves(doc: DesignDocument, group: RepeatedGroup, tolerance: float) -> list[Move]:
    """Moves that bring every member onto the robust uniform-pitch line.

    Only members that are more than 0.5 px off the line move, so one displaced item produces one
    move rather than shifting the whole run.
    """
    if group.spread(doc) <= tolerance:
        return []
    centers = group.centers(doc)
    c0, pitch = robust_pitch_fit(centers)
    moves: list[Move] = []
    for i, (cid, cur) in enumerate(zip(group.member_ids, centers, strict=True)):
        delta = (c0 + i * pitch) - cur
        if abs(delta) > 0.5:
            dx, dy = (0.0, delta) if group.axis == "column" else (delta, 0.0)
            moves.append(
                Move(cid, round(dx, 3), round(dy, 3),
                     f"pitch {group.pitches(doc)[min(i, len(centers) - 2)]:.1f}px vs uniform {pitch:.1f}px")
            )
    return moves


def spacing_moves(doc: DesignDocument, tolerance: float) -> list[Move]:
    moves: list[Move] = []
    for comp in preorder(doc):
        if comp.type not in CONTAINER_TYPES:
            continue
        for group in repeated_groups(doc, comp.id):
            moves.extend(group_moves(doc, group, tolerance))
    return moves


def apply_spacing(doc: DesignDocument, tolerance: float, max_passes: int = 2) -> int:
    total = 0
    for _ in range(max_passes):
        moves = spacing_moves(doc, tolerance)
        if not moves:
            break
        seen: set[str] = set()
        for mv in moves:
            if mv.component_id in seen:
                continue
            seen.add(mv.component_id)
            move_subtree(doc, mv.component_id, mv.dx, mv.dy)
            total += 1
    return total
