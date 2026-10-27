# Implementation plan

Loop for every iteration: **inspect → design → implement → test → measure → diagnose → improve →
verify → document**. Smallest coherent change, then regression tests. Stop and reassess after three
failed attempts at the same failure. Never weaken a test to get a pass.

| Phase | Scope | State | Exit criterion |
|---|---|---|---|
| 0 | Environment, structure, decisions | done | environment recorded (`scripts/inspect_*`), ADRs written |
| 1 | Design IR + image pipeline + deterministic detection | done | 318 passing automated tests; held-out benchmark |
| 2 | Editable renderer, editor, undo/redo, desktop workspace | done | PySide6 UI tests pass; edits update the IR |
| 3 | Evaluation + repair + closed loop | done | 337-cell matrix, 0 % regressed |
| 4 | NVIDIA/Nebius integration | tested (mock) | official rules recorded; client + policy verified against fake transport; live call runnable via `scripts/verify_nebius.py` |
| 5 | Dataset audit, manifests, pilot subset, held-out eval set | partial | manifest schema & licenses audited; synthetic generator active; 443 GB storage available |
| 6 | Compact detector trained from random init | implemented | MobileNet FPN-lite architecture & trainer loop ready; training run pending on local RTX 4050 GPU |
| 7 | Natural-language design edits (validated against the IR) | done (core) | 58 tests passed in `test_assist.py`; desktop UI prompt bar pending integration |
| 8 | React/TS frontend generation + verification | done (core) | component, page, style generators & project export verified in `test_generation_pipeline.py` |
| 9 | Python backend generation (when the app needs one) | done (core) | SQLite schema DDL, dataclass models, DB connectors, CRUD logic, and tests pass |
| 10 | Restricted execution, screenshots, repair, rollback | implemented | sandbox & verification runners implemented; unit test suite in progress |
| 11 | Performance, packaging, hackathon materials | in progress | reproducible demo & project bundler verified; standalone desktop packager pending |

## Effort allocation

About 30 % of total engineering effort is reserved for Phase 4 (integration, evaluation, reliability,
demo). It is an effort target, not a lines-of-code target; no superficial wrappers.

## Constraints that shape the plan

* Hardware: Windows 11 (AMD64), 12 CPU cores, NVIDIA GeForce RTX 4050 Laptop GPU (6 GB VRAM), PyTorch 2.6.0+cu124 (CUDA 12.4), ~443 GB free disk. Phase 6 models leverage local GPU training.
* The application never grows an API server. Remote providers are outbound clients only.
* A claim (trained, licensed, passing, integrated) is made only after it is verified and recorded.
