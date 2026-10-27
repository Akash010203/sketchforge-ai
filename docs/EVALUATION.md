# Evaluation: what is measured, how, and what the numbers do **not** mean

Two different questions are measured separately and must not be conflated:

1. **Is the detection right?** (needs ground truth) → `evaluation/component_metrics.py`,
   `scripts/evaluate_layout.py`. Only possible on generated sketches today.
2. **Is the design structurally sound?** (needs no ground truth) → the *issue* checks below,
   run on any Design IR document, including after user edits.

A visual-similarity score is **never** reported as semantic correctness.

## Issue codes (`evaluation/issues.py`)

All thresholds come from `config/evaluation.yaml`; all distances are design-space pixels (page is
1024 px wide for landscape sketches, 414 px for portrait). `measure` is the issue's size in its unit
and is always > 0. An issue's `key` (`CODE:component,ids:discriminator`) is stable across
re-evaluations so before/after comparisons are about *the same problem*.

| Code | Severity | Definition | Measure |
|---|---|---|---|
| `OVERFLOW_PARENT` | error | a component extends beyond its parent's box by more than `containment_tolerance_px` (2) | px past the worst side |
| `OVERFLOW_PAGE` | error | same, for a direct child of the page | px |
| `OVERLAP` | warning | two siblings overlap by more than `overlap_tolerance_ratio` (5 %) of the smaller area (parent/child nesting is not overlap; sliver overlaps < 8 px are trimmed at build time) | intersection ÷ smaller area |
| `MISALIGNED` | warning | sibling edges within `align_snap_radius_px` (16) of each other — i.e. "meant to be aligned" — but not within `align_tolerance_px` (2) | px off the group's anchor |
| `UNEVEN_SPACING` | warning | in a repeated group (≥ 3 similar siblings) the gaps differ by more than `spacing_tolerance_px` (4) | px deviation from the fitted pitch |
| `TEXT_OVERFLOW` | warning | *estimated* text width exceeds the box's inner width by more than 1 px | px |
| `TEXT_CLIPPED` | warning | line box (font size × line height) taller than the component | px |
| `LOW_CONTRAST` | warning | WCAG 2.x contrast of text colour vs the effective (composited) background < 4.5 | shortfall in ratio |
| `TOUCH_TARGET_SMALL` | warning | button/input shorter than 24 px, or checkbox/radio smaller than 16 px | px short |
| `FONT_TOO_SMALL` | info | font size < 10 px | px short |

Counts and summed magnitudes per code are exposed as metrics (`count.CODE`, `magnitude.CODE`) plus
`issues_total/error/warning/info`.

### Limitations of the checks

* **Text width is an estimate** (`domain/typography.py`: 0.55 em per character, plus 0.015 em per
  100 weight units above 400), roughly ±10 % of real glyph advances. `TEXT_OVERFLOW` means *probably does
  not fit*; a font engine would be needed to say more. Renderers do not clip text, so a pixel
  check would agree only approximately.
* **Alignment/spacing are intent heuristics.** Two edges 12 px apart are treated as "meant to be
  aligned"; a deliberate offset smaller than the snap radius will be flagged. Tune
  `align_snap_radius_px` for your drawings.
* **Contrast** uses WCAG relative luminance on sRGB hex colours; it ignores images and gradients
  behind text.
* **No semantic checks**: nothing here knows whether a button should be a link, or whether the
  layout is good design.

## Fidelity to the sketch (`geometry_metrics.py`)

For every visible component, the current box is compared with the box implied by its detection
(`detection.source_bbox` mapped through `metadata.source_transform`). Reported: **mean IoU**, **mean
and max position error (px)**. It measures how far edits/repairs moved the design *from the
detections*; it is **not** evidence that the detections are right.

## Pixel metrics (`image_metrics.py`)

Changed-pixel fraction, bounding box of change, and mean **SSIM** (Gaussian window, grayscale)
between two raster renders. Used to show that a patch's visual footprint is small. They say how
much changed, not whether the change is correct.

## Detection metrics (`component_metrics.py`, `evaluation/benchmark_runner.py`)

Greedy one-to-one IoU matching (threshold 0.5) between detected and ground-truth
boxes → precision, recall, F1; **type accuracy** among matched pairs; mean IoU of matched pairs;
page-frame IoU. Reported per photo condition and per layout, separately for *tuning layouts* (the
rules were adjusted while looking at these) and *held-out layouts* (never looked at).
**Synthetic only** — see KNOWN_LIMITATIONS.

## Regression policy (`config/evaluation.yaml → regression`)

A patch is accepted only if **all** hold: (1) the target issue's measure drops by ≥ 0.01 (absolute)
or it disappears; (2) no issue appears that was not there before — an issue whose key changed only
because its group changed (same code, shared component, an old issue vanished) is matched as a
*continuation*, not counted as new; (3) no existing or continued issue grows by more than 0.5;
(4) mean fidelity IoU against the sketch detections drops ≤ 0.02; (5) mean position error rises
≤ 2 px. Checks 4–5 are skipped, and the report says so, for documents without sketch provenance.

## Repair outcome labels

`IMPROVED` (fewer errors, then fewer issues) · `REGRESSED` · `NO_MEASURABLE_DIFFERENCE` ·
`UNABLE_TO_VERIFY`. Code changed ≠ quality improved: the report states which.

## Reproduce

```bash
python scripts/evaluate_layout.py     # detection benchmark  → experiments/results/detection_benchmark.json
python scripts/evaluate_repair.py     # repair matrix (~2 min) → experiments/results/repair_matrix.json
python -m pytest tests -q
```
