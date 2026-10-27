# Task ledger

Statuses: `NOT_STARTED` · `IN_PROGRESS` · `IMPLEMENTED` (code exists) · `TESTED` (an automated test
ran and passed) · `VERIFIED` (acceptance criterion measured and recorded) · `BLOCKED`.
A feature is not VERIFIED because it compiles. Updated with the 318-test run on 2026-10-19 (0 failed, 0 skipped).

## Milestone 1 — sketch → editable design → measured, verified repair

| # | Feature | Status | Evidence / acceptance |
|---|---|---|---|
| 1 | Design IR schema, validation, serialization, versioning/migrations | VERIFIED | `tests/unit/test_design_ir.py`; round-trip hash equality; unknown fields rejected |
| 2 | Safe image loading (type, size, magic bytes, pixel budget) | TESTED | `tests/unit/test_vision.py` (bad/oversized/tiny/corrupt inputs) |
| 3 | Preprocessing (illumination flattening, threshold variants, stroke width) | TESTED (real-photo regression baseline only) | CI evaluates an annotated CC0 smartphone photo; F1 0.0031, type accuracy 0.0000, mean matched IoU 0.6716 in `experiments/results/real_photo_benchmark.json`; current detector fails on grid paper and needs improvement |
| 4 | Shape / line / text-region detection and rule-based classification with ambiguity | VERIFIED (synthetic); real-photo regression baseline recorded | synthetic held-out F1 0.982, type accuracy 0.946; photographed grid-paper F1 0.0031, type accuracy 0.0000 (`experiments/results/real_photo_benchmark.json`) |
| 5 | Hierarchy, alignment, spacing and repeated-group inference → Design IR | TESTED | `layout/hierarchy.py` owns hierarchy; compatibility export in `vision/layout_inference.py`; `tests/unit/test_layout.py`, `test_sketch_to_ir.py` |
| 6 | Perspective correction (`vision/perspective.py`) | NOT_STARTED | planned; 4-point quad warp; see KNOWN_LIMITATIONS |
| 7 | Renderers: SVG, nested HTML, CSS, PNG snapshot (deterministic) | TESTED | `tests/unit/test_renderer.py` |
| 8 | Editor: undoable commands, locks, selection, property editing | TESTED | `tests/unit/test_editor.py`; exact undo to the original hash |
| 9 | Evaluator: 10 issue codes + fidelity vs sketch + SSIM/pixel metrics | TESTED | `tests/unit/test_metrics.py` |
| 10 | Repair engine: diagnose → candidates → trial → regression check → accept / exact rollback | VERIFIED (synthetic) | 337-cell matrix: 97.0 % repaired, 0 % regressed |
| 11 | Orchestration: step registry, budgets, stopping rules, history, cancel | TESTED | `tests/unit/test_repair.py` (limits, no-progress, 3-attempt cap) |
| 12 | Application controller (Qt-free), events, background tasks, project store | TESTED | `tests/integration/test_controller.py` |
| 13 | Desktop UI (tree, canvas with drag/resize, properties, measure & repair, code) | TESTED | `tests/integration/test_ui_smoke.py` (offscreen Qt, 8 tests) |
| 14 | CLI `demo` / `gui` / `info`, sample sketches, reproducible demo | VERIFIED | `tests/end_to_end/test_first_demo.py`; README steps run |
| 15 | Before/after report (JSON, Markdown, PNG comparison) | VERIFIED | demo output inspected |

**Milestone 1 exit criteria**: launches ✔ (offscreen-verified; no interactive display available in the
build environment) · import ✔ · preprocessing + detection ✔ · valid IR ✔ · renderer ✔ · editable ✔ ·
evaluator measures a known issue ✔ · repair fixes predefined issues ✔ · before/after recorded ✔ ·
automated tests ✔ · README reproduces the demo ✔.
Caveat: the sample sketches are **synthetic**; no real photographed sketch has been tested.

## Later phases

| Phase | Item | Status | Notes |
|---|---|---|---|
| 4 | Verify official NVIDIA/Nebius hackathon rules | VERIFIED | recorded in `docs/NEBIUS_NVIDIA_INTEGRATION.md` §1 (deadline Fri 30 Oct 2026 10:00 PT; Apache-2.0/MIT/MPL-2.0 licence required; hosting our own server is excluded) |
| 4 | Provider interface + isolated `integrations/nebius/` client, consent gate, privacy limits | TESTED | 32 tests against in-process fake transport (`tests/integration/test_nebius_integration.py`). Live call pending `NEBIUS_API_KEY`. |
| 4 | Live verification (`scripts/verify_nebius.py`) | IMPLEMENTED | runnable with `NEBIUS_API_KEY` on a networked machine |
| 4 | Model-vs-local benchmark (3 arms) | TESTED | `assist/edit_benchmark.py` and `scripts/run_visual_benchmark.py` implemented; tested via `tests/unit/test_edit_benchmark.py` on 58 tasks (oracle 82.8%, local 58.6%). Model arm pending live key. |
| 5 | Dataset audit, manifest schema, pilot subset | PARTIAL | Manifest and adapters implemented; 1,000 WebSight image/HTML records normalized under `datasets/processed/websight-v02/`. They lack component boxes and are not detector training samples. DrawnUI files are not present locally. |
| 5 | Synthetic data generator (original) | IMPLEMENTED | 500 examples generated with seed 42 (plus 10 earlier examples); PNG/JSON pairs in `datasets/synthetic/`. |
| 6 | Train compact detector from random init | PARTIAL | A 10-epoch CUDA run was reported with best validation loss 0.3606 at epoch 5. Workspace inspection found `best.pt` still points to an earlier checkpoint (epoch 5, loss 0.147449) because prior-run history dominated pruning; checkpoint manager now starts fresh per run. Rerun manually to save the reported run's actual best weights. IoU/mAP remain unmeasured. |
| 6 | Layout prediction model | IMPLEMENTED | Compact semantic segmentation model, paired-label dataset, and inference wrapper in `models/layout_model/`; no trained layout checkpoint yet. |
| 6 | Local hybrid retrieval | IMPLEMENTED | Document loader, BM25 lexical index, vector index, metadata filters, rank fusion, and retrieval metrics in `retrieval/`. Default vectorizer is deterministic feature hashing; callers can supply a local embedding function. |
| 5 | External dataset processing | PARTIAL | `scripts/process_datasets.py` converts WebSight image/HTML and optional DrawnUI images/annotations to normalized records. DrawnUI processing awaits local source files. |
| 7 | Natural-language edits: plan schema, summary, local parser, model planner, verified apply | TESTED | `tests/unit/test_assist.py` (58 tests pass). Desktop UI "Ask" prompt bar pending integration. |
| 8 | Frontend generation (React/TS, HTML/CSS) | TESTED | `generation/frontend/` (component, page, style generators, project export); verified via `tests/test_generation_pipeline.py`. |
| 9 | Backend generation (SQLite DDL, models, CRUD logic, tests) | IMPLEMENTED | Split across `schema_generator.py`, `database_generator.py`, `business_logic_generator.py`, and `test_generator.py`; existing public imports remain available. Regression tests were not rerun after this refactor. |
| 10 | Restricted execution + full-app verification | TESTED | Unit coverage in `tests/unit/test_execution.py` and `test_verification.py`; generated SQLite backend and its generated CRUD tests run in the sandbox in `tests/end_to_end/test_generated_project.py`. |
| 11 | Performance + packaging | PARTIAL | `scripts/bundle_project.py` (one-file bundle) and a Windows PyInstaller one-file GUI executable recipe are implemented; an actual `.exe` build still needs a Windows environment with `.[ui]` and PyInstaller installed. |

## Needs the owner

* Provide `NEBIUS_API_KEY` and run `scripts/verify_nebius.py` on a machine that can reach Nebius Token Factory.
* Register and submit on Devpost before the deadline; read the full Official Rules.

## Next single action

Execute `pip install PySide6-Essentials openai` (without invalid index flags) to enable full desktop UI and mock provider test execution, then implement perspective correction (`src/sketchforge/vision/perspective.py`).
