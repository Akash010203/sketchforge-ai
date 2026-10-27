"""Preprocessing: choose a binarization variant and produce a clean ink mask.

Several thresholding variants are tried and scored; the best-scoring one is used. The score is a
transparent heuristic (plausible ink coverage, little speckle), recorded in the result so the
choice can be inspected and ablated.

Real smartphone photos introduce per-region illumination shifts (shadows, vignetting, paper grain)
that global Otsu thresholding cannot handle. ``flatten_local_illumination`` cancels these effects
before any variant runs, using morphological dilation to estimate the local background brightness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from sketchforge.exceptions import PreprocessingError
from sketchforge.vision.morphology import (
    close_gaps,
    estimate_stroke_width,
    remove_small_components,
    speckle_fraction,
)
from sketchforge.vision.normalization import NormalizedImage
from sketchforge.vision.thresholding import VARIANTS

TARGET_INK_RATIO = 0.025  # typical share of a page covered by pen strokes in a wireframe

# Size of the rectangular dilation kernel used to estimate local background brightness.
# Must be large enough to bridge over the widest expected ink stroke (~10-15 px on a 1024 px image)
# but not so large that it smears shadow boundaries.  40 px is a well-tested value.
_BG_KERNEL_SIZE: int = 40


@dataclass
class PreprocessResult:
    ink: np.ndarray  # uint8 mask, 255 = ink, gaps bridged, specks removed
    variant: str
    variant_scores: dict[str, float]
    stroke_width: float  # working pixels
    ink_ratio: float
    notes: list[str] = field(default_factory=list)


def score_variant(mask: np.ndarray) -> float:
    """Higher is better. Penalizes implausible ink coverage and speckle."""
    ratio = float(np.count_nonzero(mask)) / mask.size
    if ratio <= 0:
        return -10.0
    coverage_penalty = abs(math.log(ratio / TARGET_INK_RATIO))
    if ratio > 0.25:
        coverage_penalty += 3.0  # almost certainly a bad threshold (paper counted as ink)
    return -coverage_penalty - 2.0 * speckle_fraction(mask)


# Minimum fraction of an axis that a line must span to be considered a ruled paper line.
# A genuine UI border (card edge, input box) rarely stretches beyond ~60% of a 1080 px image;
# most notebook / legal-pad lines run edge-to-edge (>90%). 0.65 is a safe discriminating value.
_RULED_LINE_SPAN_FRACTION = 0.65

# A notebook page typically has 20-40 ruled lines; legal pads have ≥12.
# Fewer than this and the "repetition" could simply be a grid of UI components.
_RULED_LINE_MIN_CENTERS = 12

# The centers of ruled lines must collectively span more than this fraction of the perpendicular
# dimension. If they only cover 30% of the page height, the rows are a UI table, not ruling.
_RULED_LINE_COVERAGE_FRACTION = 0.50


def suppress_ruled_lines(mask: np.ndarray) -> tuple[np.ndarray, str | None]:
    """Remove long, regularly spaced paper rules from a binary ink mask.

    Suppression is gated on **three independent criteria** that must all pass:

    1. **Span**: each candidate line must traverse > 65 % of the image width/height.
       A single UI border box rarely reaches this threshold.
    2. **Count**: ≥ 12 distinct rule centers must be found.
       A login form with a few input separators will never reach 12.
    3. **Coverage**: the set of rule centers must span > 50 % of the perpendicular
       dimension, ensuring the pattern fills the page rather than a sub-region.

    The detected line pixels are removed without eroding neighboring strokes, which
    helps preserve handwriting that crosses a rule.
    """
    h, w = mask.shape
    detected = np.zeros_like(mask)
    directions: list[str] = []
    for orientation, axis_len, perp_len in (
        ("horizontal", w, h),
        ("vertical", h, w),
    ):
        # ---------- build the morphological line detector ----------
        # The structuring element must be longer than 65 % of the axis so that only
        # strokes reaching nearly across the full dimension survive the OPEN.
        kernel_len = max(25, int(round(_RULED_LINE_SPAN_FRACTION * axis_len)))
        kernel_shape = (
            (kernel_len, 1) if orientation == "horizontal" else (1, kernel_len)
        )
        opened = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, kernel_shape),
        )

        # ---------- project onto the perpendicular axis ----------
        # For horizontal lines, sum along axis=1 (columns) → profile over rows.
        profile = (opened > 0).sum(axis=1 if orientation == "horizontal" else 0)

        # A row/column qualifies as belonging to a rule only if its projected ink
        # count is itself substantial (> 65 % of the relevant dimension).
        span_threshold = int(round(_RULED_LINE_SPAN_FRACTION * axis_len))
        indices = np.flatnonzero(profile >= span_threshold)
        if indices.size == 0:
            continue

        # ---------- cluster adjacent pixels into single rule centers ----------
        gaps = np.diff(indices)
        groups = np.split(indices, np.flatnonzero(gaps > 2) + 1)
        centers = np.array([float(g.mean()) for g in groups if g.size])

        # Criterion 2: need at least _RULED_LINE_MIN_CENTERS distinct lines.
        if centers.size < _RULED_LINE_MIN_CENTERS:
            continue

        # Criterion 3: the centers must span more than 50 % of the perpendicular dim.
        span_covered = float(centers[-1] - centers[0])
        if span_covered < _RULED_LINE_COVERAGE_FRACTION * perp_len:
            continue

        # ---------- verify regular spacing (it must look like a ruling) ----------
        spacings = np.diff(centers)
        median_spacing = float(np.median(spacings))
        if median_spacing < 4 or median_spacing > 0.12 * perp_len:
            continue
        mad = float(np.median(np.abs(spacings - median_spacing)))
        if mad / median_spacing > 0.25:  # tighter jitter tolerance than before
            continue

        detected = cv2.bitwise_or(detected, opened)
        directions.append(orientation)

    if not directions:
        return mask, None
    filtered = cv2.bitwise_and(mask, cv2.bitwise_not(detected))
    return filtered, f"suppressed repeated {' and '.join(directions)} ruled-paper lines"


# ---------------------------------------------------------------------------
# Graph-paper / grid notch filter
# ---------------------------------------------------------------------------

# Minimum energy fraction that a spectral peak must have relative to the global
# mean to be treated as a structured grid frequency rather than image content.
_NOTCH_PEAK_THRESHOLD = 6.0

# Half-width (in pixels) of each notch band around a detected grid frequency.
_NOTCH_HALF_WIDTH = 2


def suppress_grid_paper(
    mask: np.ndarray,
    min_period: int = 6,
    max_period: int = 80,
) -> tuple[np.ndarray, str | None]:
    """Attenuate periodic graph-paper mesh in a binary ink mask via FFT notch filtering.

    Algorithm
    ---------
    1. Compute the 2-D FFT magnitude spectrum of the mask.
    2. Build 1-D row- and column-summed profiles to detect dominant periodicities
       in the horizontal and vertical directions independently.
    3. For each strong periodic frequency (harmonic of the grid pitch), zero-out
       a narrow notch band (±``_NOTCH_HALF_WIDTH`` rows/columns) in the FFT.
    4. Reconstruct via inverse FFT and re-binarize with Otsu thresholding.

    The notch is kept narrow (default ±2 pixels in frequency space) so that
    irregular handwriting strokes — which have broad spectral energy — are
    preserved while the sharp, narrowband grid signal is removed.

    Parameters
    ----------
    mask:
        Binary uint8 image (255 = ink, 0 = paper).
    min_period / max_period:
        Range of grid pitches (pixels) to consider.  Periods outside this range
        are ignored to avoid attacking image content.

    Returns
    -------
    Filtered mask and an optional human-readable note, or (mask, None) if no
    periodic grid was detected.
    """
    h, w = mask.shape
    float_img = mask.astype(np.float32) / 255.0

    # Pad to the next power-of-two for speed.
    fh = cv2.getOptimalDFTSize(h)
    fw = cv2.getOptimalDFTSize(w)
    padded = np.zeros((fh, fw), dtype=np.float32)
    padded[:h, :w] = float_img

    # 2-D FFT → magnitude spectrum (log-compressed for peak detection).
    dft = np.fft.rfft2(padded)  # shape (fh, fw//2+1)
    magnitude = np.abs(dft)

    # DC component spans [0,0]; shift frequencies so DC is at index 0 in rows
    # but keep the half-spectrum in columns (rfft2 layout).
    row_profile = magnitude.sum(axis=1)  # energy per row-frequency
    col_profile = magnitude.sum(axis=0)  # energy per col-frequency

    def _detect_grid_frequencies(
        profile: np.ndarray,
        dim: int,
    ) -> list[int]:
        """Return frequency indices (in rfft space) of suspected grid harmonics."""
        # Convert period bounds to frequency-index bounds.
        # freq_index = dim / period  (rfft layout: index 0 = DC, 1 = 1 cycle/image …)
        f_min = max(1, int(dim / max_period))
        f_max = min(len(profile) - 1, int(dim / min_period) + 1)
        if f_min >= f_max:
            return []
        band = profile[f_min:f_max]
        if band.size == 0:
            return []
        mean_energy = float(band.mean())
        if mean_energy == 0:
            return []
        # A grid peak must be _NOTCH_PEAK_THRESHOLD × the mean band energy.
        threshold = _NOTCH_PEAK_THRESHOLD * mean_energy
        peaks = np.flatnonzero(band >= threshold) + f_min  # global freq indices
        return peaks.tolist()

    row_freqs = _detect_grid_frequencies(row_profile, fh)
    col_freqs = _detect_grid_frequencies(col_profile, fw)

    if not row_freqs and not col_freqs:
        return mask, None

    # Apply notches: zero out the detected frequency bands.
    notched = dft.copy()
    hw = _NOTCH_HALF_WIDTH
    for fi in row_freqs:
        lo, hi = max(0, fi - hw), min(notched.shape[0], fi + hw + 1)
        notched[lo:hi, :] = 0.0
    for fi in col_freqs:
        lo, hi = max(0, fi - hw), min(notched.shape[1], fi + hw + 1)
        notched[:, lo:hi] = 0.0

    # Reconstruct and crop back to original size.
    reconstructed = np.fft.irfft2(notched)[:h, :w]
    reconstructed = np.clip(reconstructed, 0.0, 1.0)
    img_u8 = (reconstructed * 255).astype(np.uint8)

    # Re-binarize with Otsu; fall back to the original mask if Otsu fails.
    _, filtered = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if filtered is None or not filtered.any():
        return mask, None

    directions: list[str] = []
    if row_freqs:
        directions.append("horizontal")
    if col_freqs:
        directions.append("vertical")
    note = f"notch-filtered periodic grid ({', '.join(directions)} frequencies)"
    return filtered, note


def flatten_local_illumination(gray: np.ndarray) -> np.ndarray:
    """Cancel shadows, vignetting, and paper-grain brightness shifts from a smartphone photo.

    Unlike the :func:`~sketchforge.vision.normalization.flatten_illumination` routine, which uses
    MORPH_CLOSE (and therefore requires the kernel to be *smaller* than any genuine stroke gap),
    this variant uses MORPH_DILATE with a large rectangular kernel.  Dilation propagates the
    *brightest* neighbouring pixel in every direction, so it naturally fills over dark ink strokes
    and produces a smooth estimate of the locally varying paper brightness, even for thick pen
    strokes or dense hatching.

    Algorithm
    ---------
    1. Dilate the grayscale image with a ``_BG_KERNEL_SIZE × _BG_KERNEL_SIZE`` rectangle to
       produce a background estimate ``bg`` in which all ink strokes have been erased by the
       surrounding paper brightness.
    2. Divide the original image by ``bg`` pixel-wise (``cv2.divide`` with scale=255) so that
       dark ink becomes a consistent fraction of the local background regardless of global
       lighting conditions.
    3. Clip to [0, 255] and return as uint8.

    Parameters
    ----------
    gray:
        Uint8 grayscale image (BGR-to-gray conversion already applied).

    Returns
    -------
    Uint8 grayscale image in which the paper background is approximately uniform (~255) and
    ink strokes are consistently dark, suitable for any of the VARIANTS threshold functions.
    """
    k = _BG_KERNEL_SIZE
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    # MORPH_DILATE erases ink (dark) by expanding bright neighbours → local paper estimate.
    bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
    # Guard against pathologically dark images (all-black patch → bg could be 0).
    bg = np.maximum(bg, 1)
    # Divide out illumination: bright paper → ~255, dark ink → small fraction of paper.
    flat = cv2.divide(gray, bg, scale=255)
    return flat


def suppress_grid_background(gray: np.ndarray, stroke_px: float) -> np.ndarray:
    """Remove a thin, regularly spaced horizontal/vertical grid from grayscale paper.

    Morphological openings isolate long thin lines. Their projected centers must form a
    regular lattice in both directions before any pixels are removed, so ordinary UI
    borders and isolated long strokes remain intact.
    """
    if gray.ndim != 2 or gray.size == 0:
        return gray
    line_len = max(3, int(stroke_px * 6))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (line_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, line_len))
    dark_ink = 255 - gray
    h_lines = cv2.morphologyEx(dark_ink, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(dark_ink, cv2.MORPH_OPEN, v_kernel)

    def periodic_centers(profile: np.ndarray) -> tuple[np.ndarray, float] | None:
        active = np.flatnonzero(profile >= max(2, int(0.45 * profile.max())))
        if active.size < 8:
            return None
        groups = np.split(active, np.flatnonzero(np.diff(active) > 2) + 1)
        centers = np.array([g.mean() for g in groups if g.size >= 1])
        if centers.size < 8:
            return None
        gaps = np.diff(centers)
        pitch = float(np.median(gaps))
        if pitch < 4 or pitch > 100:
            return None
        if float(np.median(np.abs(gaps - pitch))) / pitch > 0.20:
            return None
        return centers, pitch

    row_profile = (h_lines > 0).sum(axis=1)
    col_profile = (v_lines > 0).sum(axis=0)
    rows = periodic_centers(row_profile)
    cols = periodic_centers(col_profile)
    if rows is None or cols is None:
        return gray
    # Require both line families to cover most of their respective image axes.
    if (rows[0][-1] - rows[0][0] < 0.5 * gray.shape[0]
            or cols[0][-1] - cols[0][0] < 0.5 * gray.shape[1]):
        return gray

    grid = cv2.bitwise_or(h_lines, v_lines)
    grid = cv2.dilate(grid, np.ones((3, 3), dtype=np.uint8))
    return cv2.inpaint(gray, grid, max(1.0, float(stroke_px)), cv2.INPAINT_TELEA)


def preprocess(
    norm: NormalizedImage,
    force_variant: str | None = None,
    close_kernel: int | None = None,
) -> PreprocessResult:
    if force_variant is not None and force_variant not in VARIANTS:
        raise PreprocessingError(f"unknown threshold variant {force_variant!r}")
    # --- Local illumination flattening (mobile-photo robustness) --------------------------------
    # Apply a dilation-based local background cancellation on top of the already-normalized gray
    # channel.  This second pass specifically targets shadows and phone vignetting that survive
    # the MORPH_CLOSE-based flatten_illumination() in normalization.normalize().
    # The result is passed to every threshold variant, making all of them robust to real photos.
    locally_flat = flatten_local_illumination(norm.gray)
    locally_flat = suppress_grid_background(locally_flat, stroke_px=3.0)
    candidates = {name: fn(locally_flat) for name, fn in VARIANTS.items()}
    scores = {name: round(score_variant(mask), 4) for name, mask in candidates.items()}
    chosen = force_variant or max(scores, key=lambda k: scores[k])
    raw = candidates[chosen]

    notes: list[str] = []
    raw, ruled_note = suppress_ruled_lines(raw)
    if ruled_note:
        notes.append(ruled_note)
    # Second pass: attenuate periodic graph-paper / grid mesh via FFT notch filter.
    # This handles the 2-D case (e.g. squared paper) that the morphological filter misses.
    raw, notch_note = suppress_grid_paper(raw)
    if notch_note:
        notes.append(notch_note)
    despeckled = remove_small_components(raw, min_area=10)
    stroke_width = estimate_stroke_width(despeckled)
    # Bridge only the 1-3 px gaps left at hand-drawn corners. A larger kernel would fill the
    # triangles of an X-marked image box and the inside of small checkboxes.
    kernel = close_kernel if close_kernel is not None else max(3, round(0.5 * stroke_width) | 1)
    closed = close_gaps(despeckled, kernel)
    ink = remove_small_components(closed, min_area=max(12, int(2.5 * stroke_width)))

    ratio = float(np.count_nonzero(ink)) / ink.size
    if ratio < 0.0008:
        raise PreprocessingError(
            "almost no ink was found; the sketch may be blank, too faint, or too small"
        )
    if ratio > 0.40:
        raise PreprocessingError(
            "the image is mostly dark after thresholding; the photo may be underexposed or "
            "the background is not a light sheet of paper"
        )
    if ratio > 0.2:
        notes.append(f"high ink coverage ({ratio:.0%}); detection quality may be poor")
    return PreprocessResult(
        ink=ink,
        variant=chosen,
        variant_scores=scores,
        stroke_width=stroke_width,
        ink_ratio=ratio,
        notes=notes,
    )


def to_gray_u8(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
