# Implementation plan

Each iteration follows this loop: **inspect → design → implement → test → measure → diagnose → improve → verify → document**. Make the smallest coherent change and add regression tests. If the same failure persists after three attempts, stop and reassess the approach. Never weaken a test just to make it pass.

| Phase | Scope | State | Exit criterion |
|---|---|---|---|
| 0 | Environment, structure, and decisions | Done | Environment recorded in `scripts/inspect_*`; ADRs written |
| 1 | Design IR, image pipeline, and deterministic detection | Done | 318 automated tests passing; held-out benchmark completed |
| 2 | Editable renderer, editor, undo/redo, and desktop workspace | Done | PySide6 UI tests pass; edits update the IR |
| 3 | Evaluation, repair, and closed-loop workflow | Done | 337-cell matrix completed; 0% regression rate |
| 4 | NVIDIA/Nebius integration | Tested with mocks | Official rules documented; client and policy checked against fake transport; live call can be run through `scripts/verify_nebius.py` |
| 5 | Dataset audit, manifests, pilot subset, and held-out evaluation set | Partial | Manifest schema and licenses audited; synthetic generator active; 443 GB storage available |
| 6 | Compact detector trained from random initialization | Implemented | MobileNet FPN-lite architecture and training loop ready; local training run on the RTX 4050 GPU pending |
| 7 | Natural-language design edits validated against the IR | Core complete | 58 tests pass in `test_assist.py`; desktop prompt bar still needs integration |
| 8 | React/TS frontend generation and verification | Core complete | Component, page, and style generators and project export verified in `test_generation_pipeline.py` |
| 9 | Python backend generation when required by the application | Core complete | SQLite schema DDL, dataclass models, database connectors, CRUD logic, and tests pass |
| 10 | Restricted execution, screenshots, repair, and rollback | Implemented | Sandbox and verification runners implemented; unit test suite in progress |
| 11 | Performance, packaging, and hackathon materials | In progress | Reproducible demo and project bundler verified; standalone desktop packager pending |

## Effort allocation

Around 30% of the total engineering effort is allocated to Phase 4, covering integration, evaluation, reliability, and the demo. This is a target for engineering time, not lines of code. The focus is on working functionality rather than superficial wrappers.

## Constraints

- **Hardware:** Windows 11 (AMD64), 12 CPU cores, NVIDIA GeForce RTX 4050 Laptop GPU with 6 GB VRAM, PyTorch 2.6.0+cu124 (CUDA 12.4), and approximately 443 GB of free disk space. Phase 6 uses the local GPU for model training.
- **Network architecture:** The application does not run an API server. Remote providers are accessed only through outbound client connections.
- **Verification:** Claims that a model is trained, a license is valid, tests pass, or an integration works must be verified and recorded before being reported as complete.
