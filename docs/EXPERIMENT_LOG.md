# Experiment log

Newest last. Every entry says what was changed, what was measured before and after, and whether the
change was to the **system** or to the **test fixture** (the latter is called out explicitly so a
better number is never mistaken for a better engine). All data is synthetic; see KNOWN_LIMITATIONS.

## E1 — Detection benchmark baseline (Phase 1)

Generator layouts: tuning = `login_page`, `dashboard`, `mobile_form`; held-out = `landing_page`,
`settings_page`. Conditions: clean, shadow, noisy, lowcontrast, blur, thin, thick. Seeds 11–13.
The classifier rules were adjusted while looking at the tuning layouts only.

## E2 — Squarish ink clusters → `image` (system change)

*Observation:* logos/icons drawn as scribbles were typed `text`/`heading`. *Change:* a large
(≥ 28 design px tall), squarish (width/height ≤ 1.4) ink cluster scores `image` 0.50 with `heading`
0.40 close behind, so it is flagged ambiguous (`vision/component_detection.py`). *Result* (commit
`947366c`): tuning type accuracy 0.970 → 0.985, held-out unchanged. The rule was written while looking
at tuning layouts, so the tuning gain is optimistic; the unchanged held-out figure is the honest one.
Also: `align_snap_radius_px` 24 → 16 (fewer false "meant to be aligned" groupings).

## E3 — Detection benchmark, current (`scripts/evaluate_layout.py`, seeds 11–13)

| Set | Sketches | F1 | Precision | Recall | Type acc. | Mean IoU | Failures | ms/sketch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tuning layouts | 63 | 0.973 | 0.972 | 0.974 | 0.985 | 0.840 | 0 | 157 |
| **Held-out layouts** | 42 | **0.982** | 0.978 | 0.986 | **0.946** | 0.835 | 0 | 164 |

By condition (held-out F1 / type acc.): clean 1.000 / 0.938 · shadow 1.000 / 0.938 · noisy 1.000 / 0.941 ·
lowcontrast 1.000 / 0.938 · blur 0.984 / 0.957 · thick 0.973 / 0.953 · **thin 0.915 / 0.958** (weakest:
stroke breaks split text lines). Remaining type errors: card↔container, checkbox↔radio, text↔heading.
Full table: `experiments/results/detection_benchmark.json`.

## E4 — Repair engine development (system changes, each found by a failing real run)

| Symptom | Cause | Fix |
|---|---|---|
| Crash `BBox width must be > 0 (h=1e-13→0)` | float slivers in `intersection` | geometry computes areas from raw floats; `intersection` returns `None` below 1e-3; regression test |
| Accepted patch created a new `MISALIGNED` | shortest translation put an input flush with a card edge | `translate_into_container` offers an *aligned* candidate (shared alignment line) before *minimal* |
| Valid repair rejected: "3 new issues" | regrouped `UNEVEN_SPACING` keys changed identity | regression check matches **continuations** (same code, shared component, old issue vanished) |
| Baseline 3.9 px label/radio overlap | detection sliver | build-time `trim_slivers` plus a "trim" repair candidate |
| Dashboard overlap needing a pitch restore | one member of a repeated row displaced | `restore_pitch` candidate for runs of ≥ 4 similar siblings |
| Engine fixed small things first and stalled | planner ordered by magnitude | coarse-to-fine priority: overflow < overlap < text/touch < misaligned < spacing < contrast/font |
| Unfixable text overflow "repaired" by shrinking to an unreadable size | partial font shrink accepted | `shrink_font_to_floor` requires a *full* fit; test `test_unfixable_overflow_is_reported_not_papered_over` |

## E5 — Repair matrix, run 1 (before the fixture fix)

Layouts × conditions {clean, shadow, blur, noisy, thin} × seeds {11, 12} × 7 fault kinds = 350
cells, 13 skipped because the layout cannot host that fault (e.g. no repeated group of ≥ 3 items for
`spacing`) → **337 cells**. Fault detected 98.8 %, fully repaired 95.6 %, no issues left 93.5 %,
**regressed 0.0 %**, median 283 ms. `text_overflow` repaired only 88 %.

## E6 — Injected text overflow was sometimes impossible to repair (fixture change)

*Diagnosis (mobile_form, seed 11):* the injector lengthened a 12 px input label to 1.15× the available
width in whole " ab" tokens, overshooting by up to ~6 %; with the 10 px font floor the largest
fixable overflow is ×1.2, and the box already spanned its card so it could not widen. No strategy
could fix it, so the engine correctly reported it unfixed.
*Change (to the injector, not the engine):* the injected overflow is now sized to stay within what a
font shrink could absorb (`0.92 × font / floor`), and must still overflow by > 2 %.
*Disclosure:* this makes the benchmark slightly easier on `text_overflow`; the engine's behaviour on
truly unfixable overflow is kept covered by its own unit test.

## E7 — Repair matrix, run 2 (current, `scripts/evaluate_repair.py`)

| | Run 1 | Run 2 |
|---|---:|---:|
| Cells (skipped) | 337 (13) | 337 (13) |
| Fault detected | 98.8 % | 98.8 % |
| Fully repaired (injected fault gone, no regression) | 95.6 % | **97.0 %** |
| No issues left at all | 93.5 % | **95.0 %** |
| Regressed | 0.0 % | **0.0 %** |
| Median repair time | 283 ms | 308 ms |

By kind (repaired): spacing 100 %, text_overflow 98 %, small_control 98 %, low_contrast 98 %,
misalignment 96 %, overflow 96 %, overlap 94 % (80 % with nothing left over).
By condition: clean/shadow/noisy 100 %, blur 97 %, **thin 88 %**. By layout: mobile_form 100 %,
dashboard/landing/login 98–99 %, **settings_page 88 %** (77 % clean).

*Where it still fails:* almost all remaining failures are `settings_page` under `thin` strokes, where
the **baseline** detection already contains several overlapping text boxes (checkbox/heading/text
overlaps from split text lines). The engine repairs the injected fault but then stalls on
pre-existing detection artefacts (no-progress rule) instead of redesigning. A few `blur` cases leave a
`MISALIGNED` heading after a misalignment injection ("no applicable strategy left").
These are reported as failures, not hidden. Full rows: `experiments/results/repair_matrix.json`.

## E8 — Hardware envelope (`scripts/inspect_environment.py`, `inspect_storage.py`)

2 CPU cores, 7.84 GB RAM, no GPU, Python 3.13.16, Node 22.22, PySide6 6.12, OpenCV 5.0, NumPy 2.5,
PyTorch not installed; 29.4 GB free disk (planning budget 14.7 GB). Demo wall time ≈ 1.3 s.

## Open questions

1. How do real phone photos of hand-drawn sketches compare? (needs a small real set, Phase 5)
2. Does a model trained from scratch (Phase 6) beat the heuristics on the `thin`/`blur` conditions?
3. Should repair be allowed to fix baseline detection artefacts (merge split text boxes) rather than
   only injected faults?
