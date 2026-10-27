"""Sibling relationships on a Design IR document: alignment clusters and repeated groups.

These definitions are shared by layout refinement, the evaluator and the repair engine, so
"misaligned" and "inconsistent spacing" mean exactly one thing everywhere.

Alignment. Two siblings are *related* when they are stacked (they overlap horizontally and do not
overlap vertically) or side by side (the reverse). Stacked siblings can align on left / center_x /
right edges; side-by-side siblings on top / center_y / bottom. Edges of related siblings that are
within ``radius`` px are clustered; a cluster whose members disagree by more than ``tolerance``
px has outliers. A sibling that lines up with a partner on *any* edge of the family is considered
aligned (a checkbox and its label may share a centre line but not a top edge).

Spacing. A repeated group is a run of at least three consecutive similar siblings (same type,
similar size, same column or row). Its pitch is the distance between consecutive centres, and the
group is consistent when the pitches agree within a tolerance.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sketchforge.design_ir.geometry import horizontal_gap, vertical_gap, x_overlap, y_overlap
from sketchforge.design_ir.schema import BBox, Component, ComponentType, DesignDocument

STACK_EDGES = ("left", "center_x", "right")
ROW_EDGES = ("top", "center_y", "bottom")
_EXCLUDED = {ComponentType.DIVIDER, ComponentType.PAGE}


def edge_value(box: BBox, kind: str) -> float:
    return {
        "left": box.x, "center_x": box.cx, "right": box.x2,
        "top": box.y, "center_y": box.cy, "bottom": box.y2,
    }[kind]


def shift_to_edge(box: BBox, kind: str, target: float) -> tuple[float, float]:
    """(dx, dy) that moves ``box`` so its ``kind`` edge sits at ``target``."""
    delta = target - edge_value(box, kind)
    return (delta, 0.0) if kind in STACK_EDGES else (0.0, delta)


def alignable_siblings(doc: DesignDocument, parent_id: str) -> list[Component]:
    return [c for c in doc.children_of(parent_id) if c.visible and c.type not in _EXCLUDED]


def _related(a: BBox, b: BBox, family: str) -> bool:
    if family == "stack":
        return x_overlap(a, b) >= 0.4 * min(a.w, b.w) and vertical_gap(a, b) >= -1.0
    return y_overlap(a, b) >= 0.4 * min(a.h, b.h) and horizontal_gap(a, b) >= -1.0


@dataclass(frozen=True)
class Misalignment:
    parent_id: str
    component_id: str
    edge: str
    current: float
    target: float
    partners: tuple[str, ...]

    @property
    def residual(self) -> float:
        return abs(self.current - self.target)


def _support(kids: list[Component], index: int, family: str, tol: float) -> int:
    """How many siblings line up with kids[index] (any edge of the family) within tol."""
    edges = STACK_EDGES if family == "stack" else ROW_EDGES
    me = kids[index]
    count = 0
    for j, other in enumerate(kids):
        if j == index or not _related(me.bbox, other.bbox, family):
            continue
        if any(abs(edge_value(me.bbox, k) - edge_value(other.bbox, k)) <= tol for k in edges):
            count += 1
    return count


def find_misalignments(
    doc: DesignDocument, parent_id: str, radius: float, tolerance: float
) -> list[Misalignment]:
    kids = alignable_siblings(doc, parent_id)
    found: list[Misalignment] = []
    for family, kinds in (("stack", STACK_EDGES), ("row", ROW_EDGES)):
        support = [_support(kids, i, family, tolerance) for i in range(len(kids))]
        for kind in kinds:
            parent_of = list(range(len(kids)))

            def find(i: int, parent_of: list[int] = parent_of) -> int:
                while parent_of[i] != i:
                    parent_of[i] = parent_of[parent_of[i]]
                    i = parent_of[i]
                return i

            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    if _related(kids[i].bbox, kids[j].bbox, family) and abs(
                        edge_value(kids[i].bbox, kind) - edge_value(kids[j].bbox, kind)
                    ) <= radius:
                        parent_of[find(i)] = find(j)
            clusters: dict[int, list[int]] = {}
            for i in range(len(kids)):
                clusters.setdefault(find(i), []).append(i)
            for members in clusters.values():
                if len(members) < 2:
                    continue
                vals = {i: edge_value(kids[i].bbox, kind) for i in members}

                def anchor_rank(i: int, vals: dict[int, float] = vals, support: list[int] = support) -> tuple:
                    agree = sum(abs(vals[i] - vals[j]) <= tolerance for j in vals)
                    return (agree, support[i], kids[i].bbox.area, -i)

                anchor = max(members, key=anchor_rank)
                near = [vals[j] for j in members if abs(vals[j] - vals[anchor]) <= tolerance]
                target = statistics.median(near)
                for i in members:
                    if abs(vals[i] - target) <= tolerance:
                        continue
                    partners = [j for j in members if abs(vals[j] - target) <= tolerance]
                    other_kinds = [k for k in kinds if k != kind]
                    if any(
                        abs(edge_value(kids[i].bbox, k) - edge_value(kids[j].bbox, k)) <= tolerance
                        for j in partners
                        for k in other_kinds
                    ):
                        continue  # aligned with a partner on another edge: not a misalignment
                    found.append(
                        Misalignment(
                            parent_id, kids[i].id, kind, vals[i], target,
                            tuple(kids[j].id for j in partners),
                        )
                    )
    # One component may be flagged on several edges (left, then center_x, ...); keep the
    # smallest correction per component and family so the repair stays minimal.
    best: dict[tuple[str, str], Misalignment] = {}
    for m in found:
        key = (m.component_id, "x" if m.edge in STACK_EDGES else "y")
        if key not in best or m.residual < best[key].residual:
            best[key] = m
    return sorted(best.values(), key=lambda m: (m.component_id, m.edge))


@dataclass(frozen=True)
class RepeatedGroup:
    parent_id: str
    axis: str  # 'column' or 'row'
    member_ids: tuple[str, ...]  # ordered along the axis

    def centers(self, doc: DesignDocument) -> list[float]:
        pick = (lambda b: b.cy) if self.axis == "column" else (lambda b: b.cx)
        return [pick(doc.require(i).bbox) for i in self.member_ids]

    def pitches(self, doc: DesignDocument) -> list[float]:
        c = self.centers(doc)
        return [b - a for a, b in zip(c[:-1], c[1:], strict=True)]

    def spread(self, doc: DesignDocument) -> float:
        p = self.pitches(doc)
        return max(p) - min(p) if p else 0.0


def similar(a: Component, b: Component) -> bool:
    """Same type and similar size: could be members of one repeated group."""
    if a.type != b.type:
        return False
    text_like = a.type in (ComponentType.TEXT, ComponentType.HEADING)
    h_tol = 0.4 if text_like else 0.15
    if abs(a.bbox.h - b.bbox.h) > h_tol * a.bbox.h:
        return False
    return text_like or abs(a.bbox.w - b.bbox.w) <= 0.15 * a.bbox.w


def repeated_groups(doc: DesignDocument, parent_id: str, min_members: int = 3) -> list[RepeatedGroup]:
    kids = alignable_siblings(doc, parent_id)
    groups: list[RepeatedGroup] = []
    for axis in ("column", "row"):
        if axis == "column":
            ordered = sorted(kids, key=lambda c: (c.bbox.y, c.bbox.x))
        else:
            ordered = sorted(kids, key=lambda c: (c.bbox.x, c.bbox.y))
        chain: list[Component] = []

        def flush(chain: list[Component] = chain, axis: str = axis) -> None:
            if len(chain) >= min_members:
                groups.append(RepeatedGroup(parent_id, axis, tuple(c.id for c in chain)))

        for comp in ordered:
            if chain:
                first, last = chain[0], chain[-1]
                ok = similar(first, comp)
                if axis == "column":
                    ok = ok and x_overlap(last.bbox, comp.bbox) >= 0.5 * min(last.bbox.w, comp.bbox.w)
                    ok = ok and vertical_gap(last.bbox, comp.bbox) >= 0 and comp.bbox.y >= last.bbox.y
                else:
                    ok = ok and y_overlap(last.bbox, comp.bbox) >= 0.5 * min(last.bbox.h, comp.bbox.h)
                    ok = ok and horizontal_gap(last.bbox, comp.bbox) >= 0 and comp.bbox.x >= last.bbox.x
                if ok:
                    chain.append(comp)
                    continue
                flush()
                chain.clear()
            chain.append(comp)
        flush()
    return groups


def robust_pitch_fit(centers: list[float]) -> tuple[float, float]:
    """Fit c_i = c0 + i * pitch using the median pitch and median offset, so a single displaced
    member does not drag the others. Returns (c0, pitch)."""
    pitches = [b - a for a, b in zip(centers[:-1], centers[1:], strict=True)]
    pitch = statistics.median(pitches)
    c0 = statistics.median(c - i * pitch for i, c in enumerate(centers))
    return c0, pitch
