"""Deterministic repair rules.

Each rule implements one strategy and returns an *ordered list of candidate patches* (best first,
possibly empty). It never mutates the document. The repair loop tries a candidate, measures, and
keeps or reverts it; a rejected candidate is followed by the next one, within the per-issue limit.

Candidates are filtered with cheap geometric checks (stays inside its container, does not land on
a sibling) so attempts are not wasted on moves that are obviously wrong; the regression check
remains the actual judge.
"""

from __future__ import annotations

from collections.abc import Callable

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.geometry import (
    clamp_into,
    contains,
    intersection_area,
    translate,
    x_overlap,
    y_overlap,
)
from sketchforge.design_ir.schema import BBox, Component, ComponentType, DesignDocument
from sketchforge.domain.color_system import best_text_color, effective_background
from sketchforge.domain.typography import estimate_text_width, line_box_height
from sketchforge.evaluation.issues import Issue
from sketchforge.layout.grouping import (
    ROW_EDGES,
    STACK_EDGES,
    RepeatedGroup,
    alignable_siblings,
    edge_value,
    shift_to_edge,
    similar,
)
from sketchforge.layout.overlap import sliver_trim
from sketchforge.layout.spacing import group_moves
from sketchforge.repair import diagnosis as D
from sketchforge.repair.diagnosis import _container_box
from sketchforge.repair.patch import Patch, PropertyChange

Rule = Callable[[DesignDocument, Issue, LayoutConstraints], "list[Patch]"]


# ---------------------------------------------------------------------------- helpers
def _pos(box: BBox) -> dict[str, float]:
    return {"x": round(box.x, 3), "y": round(box.y, 3)}


def _box(box: BBox) -> dict[str, float]:
    return {"x": round(box.x, 3), "y": round(box.y, 3), "w": round(box.w, 3), "h": round(box.h, 3)}


def _move_change(cid: str, old: BBox, new: BBox) -> PropertyChange:
    return PropertyChange(cid, "position", _pos(old), _pos(new))


def _padding(comp_type: ComponentType) -> float:
    from sketchforge.evaluation.text_metrics import horizontal_padding

    return horizontal_padding(comp_type)


def _sibling_overlap(doc: DesignDocument, comp: Component, new: BBox, c: LayoutConstraints,
                     ignore: set[str] = frozenset()) -> bool:
    """Would ``comp`` at ``new`` overlap a sibling beyond the tolerance?"""
    for other in alignable_siblings(doc, comp.parent_id or doc.root_id):
        if other.id == comp.id or other.id in ignore:
            continue
        inter = intersection_area(new, other.bbox)
        if inter > 0 and inter / min(new.area, other.bbox.area) > c.overlap_tolerance_ratio:
            return True
    return False


def _dedupe(patches: list[Patch]) -> list[Patch]:
    seen: set[tuple] = set()
    out: list[Patch] = []
    for p in patches:
        sig = tuple((ch.component_id, ch.property, repr(ch.proposed)) for ch in p.changes)
        if sig not in seen:
            seen.add(sig)
            out.append(p)
    return out


# ---------------------------------------------------------------------------- containment
def _aligned_delta(doc, comp, container: BBox, axis: str, c) -> tuple[float, str] | None:
    """Displacement along ``axis`` that puts ``comp`` fully inside ``container``, clear of its
    siblings, *and* on an alignment line the siblings already use. Prefers the line shared by the
    most siblings, then the shortest move."""
    kinds = STACK_EDGES if axis == "x" else ROW_EDGES
    sibs = [s for s in alignable_siblings(doc, comp.parent_id or doc.root_id) if s.id != comp.id]
    tol = c.containment_tolerance_px
    best: tuple[tuple[int, float], float, str] | None = None
    for kind in kinds:
        for value in sorted({round(edge_value(s.bbox, kind), 3) for s in sibs}):
            dx, dy = shift_to_edge(comp.bbox, kind, value)
            new = translate(comp.bbox, dx, dy)
            delta = dx if axis == "x" else dy
            if axis == "x":
                inside = new.x >= container.x - tol and new.x2 <= container.x2 + tol
            else:
                inside = new.y >= container.y - tol and new.y2 <= container.y2 + tol
            if not inside or _sibling_overlap(doc, comp, new, c):
                continue
            support = sum(abs(edge_value(s.bbox, kind) - value) <= c.align_tolerance_px for s in sibs)
            key = (-support, abs(delta))
            if best is None or key < best[0]:
                best = (key, delta, kind)
    return None if best is None else (best[1], best[2])


def translate_into_container(doc, issue, c) -> list[Patch]:
    comp = doc.require(issue.component_ids[0])
    box = _container_box(doc, comp.id, issue.code)
    minimal = clamp_into(comp.bbox, box)
    axes = [a for a, needed in (("x", minimal.x != comp.bbox.x), ("y", minimal.y != comp.bbox.y)) if needed]
    if not axes:
        return []
    variants: list[tuple[str, float, float, list[str]]] = []
    # aligned variant: every needed axis onto a shared line (only offered if all axes have one)
    adx = ady = 0.0
    notes: list[str] = []
    ok = True
    for axis in axes:
        found = _aligned_delta(doc, comp, box, axis, c)
        if found is None:
            ok = False
            break
        delta, kind = found
        adx, ady = (delta, ady) if axis == "x" else (adx, delta)
        notes.append(f"onto the siblings' {kind} line")
    if ok:
        variants.append(("aligned", adx, ady, notes))
    variants.append(("minimal", minimal.x - comp.bbox.x, minimal.y - comp.bbox.y,
                     ["by the shortest distance"]))
    out = []
    for name, dx, dy, how in variants:
        new = translate(comp.bbox, dx, dy)
        if name == "minimal" and _sibling_overlap(doc, comp, new, c):
            continue
        out.append(Patch(
            issue.key, issue.code, D.TRANSLATE_INTO, (_move_change(comp.id, comp.bbox, new),),
            f"{comp.id} lies {issue.measure:.1f}px outside its container; move it back inside, "
            f"{' and '.join(how)}",
            f"{issue.code} on {comp.id}: {issue.measure:.1f}px -> 0px", variant=name,
        ))
    return _dedupe(out)


def shrink_into_container(doc, issue, c) -> list[Patch]:
    comp = doc.require(issue.component_ids[0])
    box = _container_box(doc, comp.id, issue.code)
    new = clamp_into(comp.bbox, box)
    if new == comp.bbox:
        return []
    return [Patch(
        issue.key, issue.code, D.SHRINK_INTO,
        (PropertyChange(comp.id, "bbox", _box(comp.bbox), _box(new)),),
        f"{comp.id} is larger than its container; clamp it to the container",
        f"{issue.code} on {comp.id}: {issue.measure:.1f}px -> 0px",
    )]


# ---------------------------------------------------------------------------- alignment & spacing
def align_to_group(doc, issue, c) -> list[Patch]:
    comp = doc.require(issue.component_ids[0])
    edge, target = str(issue.details["edge"]), float(issue.details["target"])
    dx, dy = shift_to_edge(comp.bbox, edge, target)
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return []
    new = translate(comp.bbox, dx, dy)
    return [Patch(
        issue.key, issue.code, D.ALIGN, (_move_change(comp.id, comp.bbox, new),),
        f"{comp.id} {edge} edge is {issue.measure:.1f}px from the group's shared edge; snap to it",
        f"MISALIGNED {comp.id} {edge}: {issue.measure:.1f}px -> 0px",
    )]


def equalize_pitch(doc, issue, c) -> list[Patch]:
    first = doc.require(issue.component_ids[0])
    group = RepeatedGroup(first.parent_id or doc.root_id, str(issue.details["axis"]), issue.component_ids)
    moves = group_moves(doc, group, c.spacing_tolerance_px)
    if not moves:
        return []
    changes = []
    for mv in moves:
        old = doc.require(mv.component_id).bbox
        changes.append(_move_change(mv.component_id, old, translate(old, mv.dx, mv.dy)))
    return [Patch(
        issue.key, issue.code, D.EQUALIZE, tuple(changes),
        f"{len(issue.component_ids)} repeated items have uneven pitch "
        f"({issue.details['min_pitch']}-{issue.details['max_pitch']}px); move the outlier(s) onto a uniform pitch",
        f"UNEVEN_SPACING: {issue.measure:.1f}px spread -> 0px",
    )]


def _pitch_candidate(doc, issue, a: Component, b: Component, c) -> Patch | None:
    """If the overlapping pair belongs to a column/row of >= 4 similar items, the overlap is
    probably one displaced member: move members onto the group's robust uniform pitch, which
    restores the spacing and the separation in one patch."""
    kids = alignable_siblings(doc, a.parent_id or doc.root_id)
    axis = "column" if abs(a.bbox.cy - b.bbox.cy) >= abs(a.bbox.cx - b.bbox.cx) else "row"
    members = [k for k in kids if similar(a, k) and (
        x_overlap(a.bbox, k.bbox) >= 0.5 * min(a.bbox.w, k.bbox.w) if axis == "column"
        else y_overlap(a.bbox, k.bbox) >= 0.5 * min(a.bbox.h, k.bbox.h))]
    if len(members) < 4 or a.id not in {m.id for m in members} or b.id not in {m.id for m in members}:
        return None
    members.sort(key=lambda k: k.bbox.cy if axis == "column" else k.bbox.cx)
    group = RepeatedGroup(a.parent_id or doc.root_id, axis, tuple(m.id for m in members))
    moves = group_moves(doc, group, c.spacing_tolerance_px)
    if not moves:
        return None
    changes = tuple(_move_change(mv.component_id, doc.require(mv.component_id).bbox,
                                 translate(doc.require(mv.component_id).bbox, mv.dx, mv.dy)) for mv in moves)
    return Patch(
        issue.key, issue.code, D.SEPARATE, changes,
        f"{a.id} and {b.id} are part of a run of {len(members)} similar items; the overlap comes from "
        f"uneven pitch, so move the outlier(s) onto the uniform pitch",
        f"OVERLAP {a.id}/{b.id}: {issue.measure:.0%} -> 0% and uniform spacing", variant="restore_pitch",
    )


def separate_siblings(doc, issue, c) -> list[Patch]:
    a, b = (doc.require(i) for i in issue.component_ids)
    out: list[Patch] = []
    pitch = _pitch_candidate(doc, issue, a, b, c)
    if pitch is not None:
        out.append(pitch)
    trim = sliver_trim(a, b)
    if trim is not None:
        victim, new = trim
        out.append(Patch(
            issue.key, issue.code, D.SEPARATE,
            (PropertyChange(victim.id, "bbox", _box(victim.bbox), _box(new)),),
            f"{a.id} and {b.id} overlap only shallowly (a detection sliver); trim {victim.id}'s "
            f"overlapping side instead of moving anything",
            f"OVERLAP {a.id}/{b.id}: {issue.measure:.0%} -> 0%", variant=f"trim-{victim.id}",
        ))
    options = []  # (distance, mover, fixed, dx, dy, label)
    for mover, fixed in ((a, b), (b, a)):
        parent = doc.require(mover.parent_id)
        mb, fb = mover.bbox, fixed.bbox
        for label, dist, dx, dy in (
            ("down", fb.y2 - mb.y, 0.0, fb.y2 - mb.y), ("up", mb.y2 - fb.y, 0.0, -(mb.y2 - fb.y)),
            ("right", fb.x2 - mb.x, fb.x2 - mb.x, 0.0), ("left", mb.x2 - fb.x, -(mb.x2 - fb.x), 0.0),
        ):
            if dist <= 0:
                continue
            new = translate(mb, dx, dy)
            if contains(parent.bbox, new, c.containment_tolerance_px) and not _sibling_overlap(
                    doc, mover, new, c):
                options.append((dist, mover, fixed, dx, dy, label))
    # the later-drawn element yields first (it is the one more likely to have drifted)
    options.sort(key=lambda o: (round(o[0], 1), -o[1].bbox.y, -o[1].bbox.x))
    for dist, mover, fixed, dx, dy, label in options:
        new = translate(mover.bbox, dx, dy)
        out.append(Patch(
            issue.key, issue.code, D.SEPARATE, (_move_change(mover.id, mover.bbox, new),),
            f"{mover.id} overlaps {fixed.id} by {issue.measure:.0%}; move it {label} {dist:.1f}px so they touch",
            f"OVERLAP {a.id}/{b.id}: {issue.measure:.0%} -> 0%", variant=f"{mover.id}-{label}",
        ))
    return _dedupe(out)


# ---------------------------------------------------------------------------- text
def _text_comp(doc, issue):
    comp = doc.require(issue.component_ids[0])
    return comp if comp.typography is not None and comp.text else None


def shrink_font(doc, issue, c) -> list[Patch]:
    comp = _text_comp(doc, issue)
    if comp is None:
        return []
    t = comp.typography
    avail = comp.bbox.w - 2 * _padding(comp.type) - c.text_overflow_tolerance_px
    est = estimate_text_width(comp.text, t.font_size, t.font_weight)
    new_size = round(t.font_size * avail / est - 0.05, 1)  # round down so it really fits
    if new_size < max(c.min_font_size_px, 0.75 * t.font_size) or new_size >= t.font_size:
        return []
    return [Patch(
        issue.key, issue.code, D.SHRINK_FONT,
        (PropertyChange(comp.id, "typography.font_size", t.font_size, new_size),),
        f"text of {comp.id} is {issue.measure:.0f}px too wide; reduce the font from {t.font_size:g} to {new_size:g}px",
        f"TEXT_OVERFLOW {comp.id}: {issue.measure:.1f}px -> 0px",
    )]


def widen_box(doc, issue, c) -> list[Patch]:
    comp = _text_comp(doc, issue)
    if comp is None:
        return []
    parent = doc.require(comp.parent_id)
    b = comp.bbox
    need_right = b.x2 + issue.measure + 2.0
    targets: list[tuple[str, float]] = []
    # prefer a right edge that a sibling already uses, so the wider box stays on a shared line
    for value in sorted({round(s.bbox.x2, 3) for s in alignable_siblings(doc, comp.parent_id) if s.id != comp.id}):
        if need_right <= value <= parent.bbox.x2 + c.containment_tolerance_px:
            targets.append(("snapped", value))
            break
    targets.append(("minimal", need_right))
    out = []
    for name, right in targets:
        new = BBox(x=b.x, y=b.y, w=right - b.x, h=b.h)
        if not contains(parent.bbox, new, c.containment_tolerance_px) or _sibling_overlap(doc, comp, new, c):
            continue
        out.append(Patch(
            issue.key, issue.code, D.WIDEN, (PropertyChange(comp.id, "bbox", _box(b), _box(new)),),
            f"text of {comp.id} is {issue.measure:.0f}px too wide; widen the box (keeps its left edge)"
            + (" to a right edge its siblings share" if name == "snapped" else ""),
            f"TEXT_OVERFLOW {comp.id}: {issue.measure:.1f}px -> 0px", variant=name,
        ))
    return _dedupe(out)


def shrink_font_to_floor(doc, issue, c) -> list[Patch]:
    comp = _text_comp(doc, issue)
    if comp is None or comp.typography.font_size <= c.min_font_size_px:
        return []
    t = comp.typography
    avail = comp.bbox.w - 2 * _padding(comp.type) - c.text_overflow_tolerance_px
    if estimate_text_width(comp.text, c.min_font_size_px, t.font_weight) > avail:
        return []  # even the smallest readable size would not fit: a partial fix only hurts legibility
    return [Patch(
        issue.key, issue.code, D.SHRINK_FONT_FLOOR,
        (PropertyChange(comp.id, "typography.font_size", t.font_size, c.min_font_size_px),),
        f"the text of {comp.id} needs more than a modest reduction; the minimum readable size makes it fit",
        f"TEXT_OVERFLOW {comp.id}: {issue.measure:.1f}px -> 0px",
    )]


def grow_height(doc, issue, c) -> list[Patch]:
    comp = _text_comp(doc, issue)
    if comp is None:
        return []
    need = line_box_height(comp.typography.font_size, comp.typography.line_height) + 0.5
    grown = BBox(x=comp.bbox.x, y=comp.bbox.cy - need / 2, w=comp.bbox.w, h=need)
    new = clamp_into(grown, doc.require(comp.parent_id).bbox)
    if new.h < need - c.text_overflow_tolerance_px:
        return []
    return [Patch(
        issue.key, issue.code, D.GROW_HEIGHT, (PropertyChange(comp.id, "bbox", _box(comp.bbox), _box(new)),),
        f"{comp.id} is {issue.measure:.0f}px too short for one line of text; grow it about its centre",
        f"TEXT_CLIPPED {comp.id}: {issue.measure:.1f}px -> 0px",
    )]


def shrink_font_to_fit_height(doc, issue, c) -> list[Patch]:
    comp = _text_comp(doc, issue)
    if comp is None:
        return []
    t = comp.typography
    new_size = round(comp.bbox.h / t.line_height - 0.05, 1)
    if new_size < c.min_font_size_px or new_size >= t.font_size:
        return []
    return [Patch(
        issue.key, issue.code, D.SHRINK_FONT_HEIGHT,
        (PropertyChange(comp.id, "typography.font_size", t.font_size, new_size),),
        f"{comp.id} cannot grow; reduce the font to {new_size:g}px so a line fits its height",
        f"TEXT_CLIPPED {comp.id}: {issue.measure:.1f}px -> 0px",
    )]


def recolor_text(doc, issue, c) -> list[Patch]:
    comp = doc.require(issue.component_ids[0])
    if comp.typography is None:
        return []
    bg = effective_background(doc, comp)
    new = best_text_color(bg, comp.typography.color, c.min_contrast_ratio + 0.1)
    if new == comp.typography.color:
        return []
    return [Patch(
        issue.key, issue.code, D.RECOLOR,
        (PropertyChange(comp.id, "typography.color", comp.typography.color, new),),
        f"text of {comp.id} has {issue.details['ratio']}:1 contrast; change the text colour to {new}",
        f"LOW_CONTRAST {comp.id}: {issue.details['ratio']}:1 -> >= {c.min_contrast_ratio:g}:1",
    )]


def enlarge_control(doc, issue, c) -> list[Patch]:
    comp = doc.require(issue.component_ids[0])
    b = comp.bbox
    if comp.type in (ComponentType.BUTTON, ComponentType.INPUT):
        grown = BBox(x=b.x, y=b.cy - c.min_touch_size_px / 2, w=b.w, h=c.min_touch_size_px)
    else:
        side = c.min_control_size_px
        grown = BBox(x=b.cx - max(b.w, side) / 2, y=b.cy - max(b.h, side) / 2, w=max(b.w, side), h=max(b.h, side))
    new = clamp_into(grown, doc.require(comp.parent_id).bbox)
    if new == b:
        return []
    return [Patch(
        issue.key, issue.code, D.ENLARGE, (PropertyChange(comp.id, "bbox", _box(b), _box(new)),),
        f"{comp.id} is smaller than the minimum control size; grow it about its centre",
        f"TOUCH_TARGET_SMALL {comp.id}: {issue.measure:.1f}px short -> 0px",
    )]


def raise_font_size(doc, issue, c) -> list[Patch]:
    comp = _text_comp(doc, issue)
    if comp is None:
        return []
    t = comp.typography
    return [Patch(
        issue.key, issue.code, D.RAISE_FONT,
        (PropertyChange(comp.id, "typography.font_size", t.font_size, c.min_font_size_px),),
        f"{comp.id} font {t.font_size:g}px is below the {c.min_font_size_px:g}px minimum",
        f"FONT_TOO_SMALL {comp.id}: {issue.measure:.1f}px -> 0px",
    )]


RULES: dict[str, Rule] = {
    D.TRANSLATE_INTO: translate_into_container, D.SHRINK_INTO: shrink_into_container,
    D.ALIGN: align_to_group, D.EQUALIZE: equalize_pitch, D.SEPARATE: separate_siblings,
    D.SHRINK_FONT: shrink_font, D.WIDEN: widen_box, D.SHRINK_FONT_FLOOR: shrink_font_to_floor,
    D.GROW_HEIGHT: grow_height, D.SHRINK_FONT_HEIGHT: shrink_font_to_fit_height,
    D.RECOLOR: recolor_text, D.ENLARGE: enlarge_control, D.RAISE_FONT: raise_font_size,
}
