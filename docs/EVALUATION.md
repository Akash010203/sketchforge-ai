# Evaluation: what is measured and what the results mean

SketchForge evaluates two separate aspects of a design. They should be treated independently because they answer different questions.

1. **Detection accuracy:** Are the detected components correct? This requires ground-truth data and is currently supported only for generated sketches. The relevant code is in `evaluation/component_metrics.py` and `scripts/evaluate_layout.py`.
2. **Structural quality:** Does the design have layout or accessibility issues? These checks do not require ground truth and can run on any Design IR document, including documents modified by users.

Visual similarity scores are never presented as evidence of semantic correctness.

## Issue codes and measurements

The checks are implemented in `evaluation/issues.py`. Thresholds come from `config/evaluation.yaml`, and all distances use design-space pixels. Landscape sketches have a width of 1024 px, while portrait sketches have a width of 414 px.

Every issue has a `measure` greater than zero, expressed in the relevant unit. Its stable `key`, formatted as `CODE:component,ids:discriminator`, allows the evaluator to track the same problem across repeated evaluations and compare results before and after a change.

| Issue code | Severity | What it detects | Measurement |
|---|---|---|---|
| `OVERFLOW_PARENT` | Error | A component extends beyond its parent's bounding box by more than the 2 px `containment_tolerance_px`. | Pixels beyond the worst side. |
| `OVERFLOW_PAGE` | Error | A direct child of the page extends beyond the page boundary. | Pixels beyond the boundary. |
| `OVERLAP` | Warning | Two siblings overlap by more than 5% of the smaller component's area, using `overlap_tolerance_ratio`. Parent-child nesting is excluded, and overlaps narrower than 8 px are trimmed during building. | Intersection area divided by the smaller area. |
| `MISALIGNED` | Warning | Sibling edges fall within the 16 px `align_snap_radius_px`, suggesting intended alignment, but differ by more than the 2 px `align_tolerance_px`. | Distance from the group's alignment anchor. |
| `UNEVEN_SPACING` | Warning | Gaps in a repeated group of at least three similar siblings differ by more than the 4 px `spacing_tolerance_px`. | Deviation from the fitted spacing pitch. |
| `TEXT_OVERFLOW` | Warning | Estimated text width exceeds the inner width of its component by more than 1 px. | Estimated overflow in pixels. |
| `TEXT_CLIPPED` | Warning | The estimated line box, calculated from font size and line height, is taller than its component. | Height exceeding the component. |
| `LOW_CONTRAST` | Warning | Text contrast against the effective composited background falls below the WCAG 2.x ratio of 4.5. | Shortfall in the contrast ratio. |
| `TOUCH_TARGET_SMALL` | Warning | A button or input is shorter than 24 px, or a checkbox or radio control is smaller than 16 px. | Pixels below the minimum size. |
| `FONT_TOO_SMALL` | Info | Font size is below 10 px. | Pixels below the minimum font size. |

The evaluator exposes counts and summed magnitudes for each issue through `count.CODE` and `magnitude.CODE`. Overall totals are available as `issues_total`, `issues_error`, `issues_warning`, and `issues_info`.

## Limitations of the checks

The measurements are useful for identifying likely problems, but each has limitations.

- **Text width is estimated.** `domain/typography.py` assumes an average width of 0.55 em per character, adding 0.015 em per 100 font-weight units above 400. This is roughly within ±10% of actual glyph advances. A `TEXT_OVERFLOW` finding means the text probably does not fit. Accurate verification would require a font engine. Renderers do not clip text, so pixel-based checks would only provide an approximate comparison.
- **Alignment and spacing rely on heuristics.** Two edges separated by 12 px may be treated as intended to align. A deliberate offset smaller than the snap radius can therefore trigger a warning. The `align_snap_radius_px` setting can be adjusted for different drawings.
- **Contrast calculations have limited background support.** The evaluator uses WCAG relative luminance on sRGB hexadecimal colors. It does not account for images or gradients behind text.
- **Semantic quality is not evaluated.** The checks cannot determine whether a button should link to another page or whether the overall design is appropriate for its intended purpose.

## Fidelity to the original sketch

`geometry_metrics.py` compares each visible component's current bounding box with the box derived from its detection. The original detection box, `detection.source_bbox`, is mapped through `metadata.source_transform`.

The evaluator reports:

- Mean intersection over union (IoU).
- Mean position error in pixels.
- Maximum position error in pixels.

These metrics show how far editing or repair has moved the design from the original detections. They do not establish whether those detections were correct.

## Pixel-level comparison

`image_metrics.py` compares two raster renders and reports the changed-pixel fraction, the bounding box of the changed region, and mean structural similarity (SSIM).

SSIM uses a Gaussian window on grayscale images. These metrics help estimate the visual footprint of a patch. They indicate how much the rendered output changed, not whether the change improved the design.

## Detection accuracy metrics

`component_metrics.py` and `evaluation/benchmark_runner.py` evaluate detected components against ground-truth bounding boxes.

The evaluator uses greedy one-to-one IoU matching with a threshold of 0.5. It reports:

- Precision, recall, and F1 score.
- Type accuracy among matched component pairs.
- Mean IoU of matched pairs.
- Page-frame IoU.

Results are separated by photo condition and layout. Tuning layouts, which were used to adjust the detection rules, are reported separately from held-out layouts that were never used during tuning.

These benchmarks currently use synthetic data only. See `KNOWN_LIMITATIONS` for the associated restrictions.

## Regression policy

The rules in `config/evaluation.yaml` under `regression` determine whether a patch is accepted. All five conditions must pass:

1. The target issue's measurement decreases by at least 0.01 in absolute terms, or the issue disappears.
2. No new issue appears. If an issue's key changes because its group changes, it can be matched as a continuation when it has the same code and shared component and the previous issue has disappeared.
3. No existing or continued issue increases in magnitude by more than 0.5.
4. Mean fidelity IoU against the sketch detections decreases by no more than 0.02.
5. Mean position error increases by no more than 2 px.

The last two checks are skipped when a document has no sketch provenance. The evaluation report explicitly records when they are skipped.

## Repair outcome labels

Each repair receives one of four outcome labels:

- `IMPROVED`: Fewer errors, followed by fewer issues.
- `REGRESSED`: The repair made the measured outcome worse.
- `NO_MEASURABLE_DIFFERENCE`: The evaluation found no measurable change.
- `UNABLE_TO_VERIFY`: The available measurements could not establish an outcome.

A code change alone does not count as an improvement. The report identifies the measured result.

## Reproducing the evaluation

Run these commands from the repository root:

```bash
python scripts/evaluate_layout.py
# Detection benchmark:
# experiments/results/detection_benchmark.json

python scripts/evaluate_repair.py
# Repair matrix, approximately 2 minutes:
# experiments/results/repair_matrix.json

python -m pytest tests -q
```

The first command runs the detection benchmark, the second evaluates the repair matrix, and the final command runs the test suite.
