"""Perspective correction: detect a four-point document boundary and warp it to a
rectangle.

Workflow
--------
1. Detect the largest quadrilateral contour in the ink mask that is plausibly a
   page frame (aspect ratio in range, area > minimum fraction of the image).
2. Order its four corners into top-left, top-right, bottom-right, bottom-left.
3. Compute the target rectangle dimensions (max width, max height of the quad).
4. Apply ``cv2.getPerspectiveTransform`` + ``cv2.warpPerspective`` to obtain a
   fronto-parallel, undistorted view of the page.
5. Return a ``PerspectiveResult`` with the warped BGR image, the transform matrix,
   and diagnostic information about what was found.

If no suitable quad is detected the original image is returned unchanged and
``corrected`` is ``False``.

Limitations (recorded in docs/KNOWN_LIMITATIONS.md)
----------------------------------------------------
* Only a single dominant quad is detected; pages with strong background clutter
  or multiple overlapping rectangles may fail.
* The quad finder uses area + approxPolyDP heuristics.  Very curved paper
  (heavy curl) or severe lighting cannot be recovered.
* Correction changes pixel coordinates; caller must rescale ground-truth boxes
  using ``matrix`` if required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PerspectiveResult:
    """Outcome of one perspective-correction attempt."""
    corrected: bool
    bgr: np.ndarray                      # warped BGR image (or original if not corrected)
    matrix: np.ndarray | None = None     # 3×3 homography (None when not corrected)
    quad_pts: np.ndarray | None = None   # (4, 2) float32 corners in source image
    target_size: tuple[int, int] = (0, 0)  # (width, height) of the output
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def correct_perspective(
    bgr: np.ndarray,
    *,
    min_area_fraction: float = 0.10,
    max_area_fraction: float = 0.98,
    min_aspect: float = 0.3,
    max_aspect: float = 3.5,
    approx_epsilon_frac: float = 0.02,
    min_quad_solidity: float = 0.80,
) -> PerspectiveResult:
    """Detect a page quad and return a warped, undistorted image.

    Parameters
    ----------
    bgr:
        BGR image at any resolution (original, before normalisation).
    min_area_fraction, max_area_fraction:
        Quad area must be between these fractions of the total image area.
    min_aspect, max_aspect:
        Acceptable width/height ratios for the detected quad.
    approx_epsilon_frac:
        Fraction of the contour perimeter used as the ε for ``approxPolyDP``.
    min_quad_solidity:
        Ratio of contour area to convex hull area; quads with many concavities
        are rejected.
    """
    h, w = bgr.shape[:2]
    image_area = float(h * w)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr.copy()
    # Use Canny so we detect page edges even when ink is light
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return PerspectiveResult(corrected=False, bgr=bgr, notes=["no contours found"])

    # Sort contours largest-first; only inspect the top-10 candidates
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    notes: list[str] = []
    best_quad: np.ndarray | None = None
    best_area = 0.0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area_fraction * image_area:
            break  # sorted, so nothing smaller will qualify
        if area > max_area_fraction * image_area:
            continue

        epsilon = approx_epsilon_frac * cv2.arcLength(cnt, closed=True)
        approx = cv2.approxPolyDP(cnt, epsilon, closed=True)
        if len(approx) != 4:
            continue

        # Check solidity (ratio of contour area to its hull area)
        hull = cv2.convexHull(approx)
        hull_area = cv2.contourArea(hull)
        if hull_area < 1.0:
            continue
        solidity = area / hull_area
        if solidity < min_quad_solidity:
            notes.append(f"rejected quad with solidity {solidity:.2f}")
            continue

        # Aspect-ratio check
        rect = cv2.minAreaRect(approx)
        rw, rh = rect[1]
        if rw < 1 or rh < 1:
            continue
        aspect = max(rw, rh) / min(rw, rh)
        if not (min_aspect <= aspect <= max_aspect):
            notes.append(f"rejected quad aspect {aspect:.2f}")
            continue

        if area > best_area:
            best_area = area
            best_quad = approx.reshape(4, 2).astype(np.float32)

    if best_quad is None:
        notes.append("no valid page quad detected; perspective unchanged")
        return PerspectiveResult(corrected=False, bgr=bgr, notes=notes)

    ordered = _order_corners(best_quad)
    # A clean, nearly canvas-sized rectangular border is a page outline, not camera
    # perspective. Rectifying it often crops/offsets synthetic or flatbed sketches and
    # makes a simple scale+offset source transform inaccurate.
    margin = np.minimum(ordered, np.array([w - 1, h - 1], dtype=np.float32) - ordered)
    axis_aligned = (
        abs(float(ordered[0, 1] - ordered[1, 1])) <= 3
        and abs(float(ordered[2, 1] - ordered[3, 1])) <= 3
        and abs(float(ordered[0, 0] - ordered[3, 0])) <= 3
        and abs(float(ordered[1, 0] - ordered[2, 0])) <= 3
    )
    near_canvas = float(np.max(margin[:, 0] / max(w, 1))) <= 0.04 and float(
        np.max(margin[:, 1] / max(h, 1))
    ) <= 0.04
    if axis_aligned and near_canvas:
        return PerspectiveResult(
            corrected=False, bgr=bgr,
            notes=["axis-aligned page border near image edges; perspective correction skipped"],
        )
    tl, tr, br, bl = ordered

    # Target rectangle size: maximum of the two width/height spans
    width_top = float(np.linalg.norm(tr - tl))
    width_bot = float(np.linalg.norm(br - bl))
    height_lft = float(np.linalg.norm(bl - tl))
    height_rgt = float(np.linalg.norm(br - tr))
    target_w = max(1, int(round(max(width_top, width_bot))))
    target_h = max(1, int(round(max(height_lft, height_rgt))))

    dst = np.array(
        [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(ordered.astype(np.float32), dst)
    warped = cv2.warpPerspective(bgr, M, (target_w, target_h))

    notes.append(
        f"perspective corrected: {w}×{h} → {target_w}×{target_h} "
        f"(area fraction {best_area / image_area:.2f})"
    )
    return PerspectiveResult(
        corrected=True,
        bgr=warped,
        matrix=M,
        quad_pts=ordered,
        target_size=(target_w, target_h),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Helper: order four corners TL, TR, BR, BL
# ---------------------------------------------------------------------------

def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Return corners in (top-left, top-right, bottom-right, bottom-left) order.

    Uses point sums and differences to identify corners of a convex quad.
    """
    # Among all four points pick TL/BR by smallest/largest sum,
    # TR/BL by smallest/largest difference. This is more robust.
    pts2 = pts.copy()
    s = pts2.sum(axis=1)
    d = np.diff(pts2, axis=1).flatten()
    tl = pts2[np.argmin(s)]
    br = pts2[np.argmax(s)]
    tr = pts2[np.argmin(d)]
    bl = pts2[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


# ---------------------------------------------------------------------------
# Diagnostic visualisation
# ---------------------------------------------------------------------------

def draw_quad(bgr: np.ndarray, quad_pts: np.ndarray) -> np.ndarray:
    """Draw the detected quad on a copy of *bgr* (for diagnostics)."""
    vis = bgr.copy()
    pts = quad_pts.astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(vis, [pts], isClosed=True, color=(0, 200, 0), thickness=3)
    for i, (x, y) in enumerate(quad_pts.astype(int)):
        label = ["TL", "TR", "BR", "BL"][i]
        cv2.circle(vis, (x, y), 10, (0, 0, 255), -1)
        cv2.putText(vis, label, (x + 12, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    return vis


# ---------------------------------------------------------------------------
# Inverse: map a point from the corrected image back to source coordinates
# ---------------------------------------------------------------------------

def map_point_to_source(
    pt: tuple[float, float],
    matrix: np.ndarray,
) -> tuple[float, float]:
    """Apply the *inverse* homography to map a corrected-image point to source coordinates."""
    inv = np.linalg.inv(matrix)
    src = np.array([[[pt[0], pt[1]]]], dtype=np.float32)
    out = cv2.perspectiveTransform(src, inv)
    return float(out[0, 0, 0]), float(out[0, 0, 1])


def map_bbox_to_source(
    bbox: tuple[float, float, float, float],
    matrix: np.ndarray,
) -> tuple[float, float, float, float]:
    """Map a corrected-image bounding box ``(x, y, w, h)`` to source coordinates."""
    x, y, bw, bh = bbox
    corners = [(x, y), (x + bw, y), (x + bw, y + bh), (x, y + bh)]
    mapped = [map_point_to_source(c, matrix) for c in corners]
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    mx, my = min(xs), min(ys)
    return mx, my, max(xs) - mx, max(ys) - my
