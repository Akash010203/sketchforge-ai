"""Merge shape, line and text observations into page-aware proposals.

Decides what the page itself is (a drawn frame, or the ink extent), removes emergent regions that
nobody drew (the "page body" left between a header and the frame), and separates real dividers
from the edges of rectangles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sketchforge.vision.contour_detection import Box, ShapeObservation, detect_shapes
from sketchforge.vision.line_detection import LineObservation, detect_lines
from sketchforge.vision.text_regions import TextRegion, find_text_regions

# --------------------------------------------------------------------------- #
# Grid-paper false-positive suppression constants
# --------------------------------------------------------------------------- #
# Maximum side length (px) of a candidate "micro-square" that might be confused
# with a grid cell rather than a drawn UI checkbox.
_GRID_MAX_SIDE_PX: int = 45
# A genuine grid lattice must have > this many near-identical squares to be
# suppressed.  A real checkbox group rarely exceeds ~8 items.
_GRID_MIN_COUNT: int = 15
# If the coefficient of variation of the square side lengths is below this
# threshold, the cluster is uniform enough to be a ruled grid.
_GRID_SIDE_CV_MAX: float = 0.08


@dataclass
class PageFrame:
    bbox: Box
    source: str  # 'drawn_frame' | 'ink_extent'
    shape: ShapeObservation | None = None


@dataclass
class RegionProposals:
    frame: PageFrame
    shapes: list[ShapeObservation]  # excludes the frame
    dividers: list[LineObservation]
    texts: list[TextRegion]
    stroke_width: float
    notes: list[str] = field(default_factory=list)


def filter_grid_lattice_false_positives(
    shapes: list[ShapeObservation],
    texts: list[TextRegion],
) -> tuple[list[ShapeObservation], str | None]:
    """Suppress clusters of tiny uniform squares produced by graph-paper grid intersections.

    A cluster is suppressed when **all three** criteria hold:

    1. **Size**: every square in the cluster has *both* sides ≤ ``_GRID_MAX_SIDE_PX`` px.
    2. **Count**: the cluster contains more than ``_GRID_MIN_COUNT`` squares.  UI controls
       rarely cluster beyond ~8; grid paper easily reaches 50–200 cells per A4 sheet.
    3. **Uniformity**: the coefficient of variation (std / mean) of the square side-lengths
       inside the cluster is below ``_GRID_SIDE_CV_MAX`` (8 %).  Drawn UI checkboxes in
       a real form can vary by 20-40 % because they are hand-drawn.
    4. **No drawn border or text**: none of the candidate shapes contain a TextRegion whose
       centre lies inside the shape's bounding box.  Grid cells are always empty; real
       checkbox groups nearly always have labels.

    The function never modifies the input lists; it returns a (possibly shorter) copy of
    ``shapes`` together with an optional human-readable suppression note.
    """
    if not shapes:
        return shapes, None

    # Index text centres for a fast containment test.
    text_centres: list[tuple[float, float]] = [
        (t.bbox[0] + t.bbox[2] / 2, t.bbox[1] + t.bbox[3] / 2) for t in texts
    ]

    def _has_text_inside(bbox: Box) -> bool:
        x, y, w, h = bbox
        return any(x <= cx <= x + w and y <= cy <= y + h for cx, cy in text_centres)

    # Working images are resized before contour detection, so notebook cells can be
    # larger than their source-image 15 px appearance.
    tiny_squares: list[ShapeObservation] = [
        s for s in shapes
        if s.kind in ("rect", "rounded_rect")
        and 8 <= s.bbox[2] <= _GRID_MAX_SIDE_PX
        and 8 <= s.bbox[3] <= _GRID_MAX_SIDE_PX
        and not _has_text_inside(s.bbox)
    ]

    if len(tiny_squares) <= _GRID_MIN_COUNT:
        return shapes, None  # not enough tiny squares to form a grid

    # Check side-length uniformity: use the average of w and h as the "side".
    sides = np.array([(s.bbox[2] + s.bbox[3]) / 2.0 for s in tiny_squares])
    mean_side = float(sides.mean())
    if mean_side <= 0:
        return shapes, None
    cv = float(sides.std()) / mean_side

    if cv >= _GRID_SIDE_CV_MAX:
        # High variation → these are hand-drawn checkboxes, not grid cells.
        return shapes, None

    # Perspective and contour jitter shift a cell's x position slightly between rows.
    # Measure horizontal pitch within each row, then vertical pitch between row centers.
    rows: list[list[ShapeObservation]] = []
    for shape in sorted(tiny_squares, key=lambda s: s.bbox[1] + s.bbox[3] / 2):
        cy = shape.bbox[1] + shape.bbox[3] / 2
        if not rows or cy - np.mean([s.bbox[1] + s.bbox[3] / 2 for s in rows[-1]]) > 10:
            rows.append([shape])
        else:
            rows[-1].append(shape)

    row_pitch: list[float] = []
    row_centers: list[float] = []
    for row in rows:
        if len(row) < 8:
            continue
        xs = np.sort([s.bbox[0] + s.bbox[2] / 2 for s in row])
        gaps = np.diff(xs)
        pitch = float(np.median(gaps))
        if 12 <= pitch <= 80 and float(np.median(np.abs(gaps - pitch))) / pitch <= 0.12:
            row_pitch.append(pitch)
            row_centers.append(float(np.median([s.bbox[1] + s.bbox[3] / 2 for s in row])))

    if len(row_pitch) < 8 or float(np.std(row_pitch)) / float(np.mean(row_pitch)) > 0.15:
        return shapes, None
    vertical_gaps = np.diff(sorted(row_centers))
    vertical_pitch = float(np.median(vertical_gaps))
    if (vertical_pitch < 12 or vertical_pitch > 80
            or float(np.median(np.abs(vertical_gaps - vertical_pitch))) / vertical_pitch > 0.20):
        return shapes, None

    # All criteria met: suppress the entire tiny-square cluster.
    suppressed_uids = {s.uid for s in tiny_squares}
    kept = [s for s in shapes if s.uid not in suppressed_uids]
    note = (
        f"suppressed {len(tiny_squares)} grid-lattice micro-squares "
        f"(side ≤{_GRID_MAX_SIDE_PX} px, CV={cv:.3f}, n={len(tiny_squares)})"
    )
    return kept, note


def _edges(box: Box) -> dict[str, float]:
    x, y, w, h = box
    return {"left": x, "right": x + w, "top": y, "bottom": y + h}


def _touches(box: Box, frame: Box, tol: float) -> int:
    be, fe = _edges(box), _edges(frame)
    return sum(abs(be[k] - fe[k]) <= tol for k in be)


def _center_inside(box: Box, outer: Box) -> bool:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    return outer[0] <= cx <= outer[0] + outer[2] and outer[1] <= cy <= outer[1] + outer[3]


def _line_is_shape_edge(line: LineObservation, shapes: list[ShapeObservation], tol: float) -> bool:
    for s in shapes:
        x, y, w, h = s.bbox
        if line.orientation == "h":
            coord = (line.y1 + line.y2) / 2
            lo, hi = sorted((line.x1, line.x2))
            for edge_y, (e_lo, e_hi) in ((y, (x, x + w)), (y + h, (x, x + w))):
                if abs(coord - edge_y) <= tol:
                    overlap = min(hi, e_hi) - max(lo, e_lo)
                    if overlap >= 0.6 * min(hi - lo, e_hi - e_lo):
                        return True
        else:
            coord = (line.x1 + line.x2) / 2
            lo, hi = sorted((line.y1, line.y2))
            for edge_x, (e_lo, e_hi) in ((x, (y, y + h)), (x + w, (y, y + h))):
                if abs(coord - edge_x) <= tol:
                    overlap = min(hi, e_hi) - max(lo, e_lo)
                    if overlap >= 0.6 * min(hi - lo, e_hi - e_lo):
                        return True
    return False


def build_proposals(ink: np.ndarray, stroke_width: float, min_side: int = 10) -> RegionProposals:
    notes: list[str] = []
    h_img, w_img = ink.shape
    all_shapes = detect_shapes(ink, stroke_width, min_side=min_side)

    # --- the page frame ---------------------------------------------------------------------
    frame_shape: ShapeObservation | None = None
    big = [
        s for s in all_shapes
        if s.kind in ("rect", "rounded_rect") and s.area >= 0.30 * ink.size
    ]
    if big:
        frame_shape = max(big, key=lambda s: s.area)
    if frame_shape is not None:
        frame = PageFrame(frame_shape.bbox, "drawn_frame", frame_shape)
    else:
        ys, xs = np.nonzero(ink)
        pad_x, pad_y = 0.03 * w_img, 0.03 * h_img
        x0, y0 = max(0.0, xs.min() - pad_x), max(0.0, ys.min() - pad_y)
        x1, y1 = min(float(w_img), xs.max() + pad_x), min(float(h_img), ys.max() + pad_y)
        frame = PageFrame((float(x0), float(y0), float(x1 - x0), float(y1 - y0)), "ink_extent")
        notes.append("no page outline found; page area taken from the extent of the drawing")

    # --- drop emergent / out-of-frame shapes -----------------------------------------------
    tol = max(2.0 * stroke_width, 8.0)
    fx, fy, fw, fh = frame.bbox
    shapes: list[ShapeObservation] = []
    for s in all_shapes:
        if s is frame_shape:
            continue
        if not _center_inside(s.bbox, frame.bbox):
            notes.append(f"ignored a shape outside the page frame at {tuple(round(v) for v in s.bbox)}")
            continue
        if frame_shape is not None and s.area >= 0.58 * frame_shape.area and _touches(s.bbox, frame.bbox, tol) >= 2:
            notes.append("ignored the leftover 'page body' region (not drawn as its own box)")
            continue
        shapes.append(s)

    # --- dividers: straight strokes that are not the edge of a box --------------------------
    min_len = max(40, round(0.07 * max(w_img, h_img)))
    all_lines = detect_lines(ink, stroke_width, min_length=min_len)
    edge_shapes = ([frame_shape] if frame_shape else []) + shapes
    edge_tol = 1.5 * stroke_width + 3
    dividers = [
        ln for ln in all_lines
        if _center_inside(ln.bbox, frame.bbox)
        and not _line_is_shape_edge(ln, edge_shapes, edge_tol)
    ]
    for i, ln in enumerate(dividers):
        ln.uid = i

    # --- text -------------------------------------------------------------------------------
    erase_shapes = ([frame_shape] if frame_shape else []) + shapes
    texts = [
        t for t in find_text_regions(ink, erase_shapes, all_lines, stroke_width)
        if _center_inside(t.bbox, frame.bbox)
    ]
    for i, t in enumerate(texts):
        t.uid = i

    # --- grid-paper false-positive filter --------------------------------------------------
    # Must run after text detection so the filter can check whether a tiny square
    # already contains a text label (if so, it is a real checkbox, not a grid cell).
    shapes, grid_note = filter_grid_lattice_false_positives(shapes, texts)
    if grid_note:
        notes.append(grid_note)

    return RegionProposals(frame, shapes, dividers, texts, stroke_width, notes)
