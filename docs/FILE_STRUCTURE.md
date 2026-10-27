# File structure

The repository follows the directory layout in the master engineering specification. The requested directories now exist in their specified locations. Python modules and operational documents are added when their milestone begins; planned areas are intentionally kept free of fake or empty implementation files.

## Repository map

| Path | Responsibility | Current state |
|---|---|---|
| `config/` | Application, logging, model, training, dataset, evaluation, and provider defaults | Active application/provider/evaluation settings; model/training/dataset defaults are disabled or license-gated |
| `docs/` | Architecture, implementation, Design IR, dataset, model, security, performance, and operational documentation | Architecture, Design IR, plan, dataset audit, security, integration, limitations, and experiment log exist; milestone-specific docs state current status |
| `assets/` | Icons, themes, and sample sketches | Sample sketches are implemented; icons and themes are reserved |
| `datasets/` | Dataset manifest and local raw, processed, synthetic, quarantine, and evaluation data | Manifest under `manifests/`; only synthetic sample sketches are currently used |
| `checkpoints/` | Locally trained model artifacts | Component detector checkpoint exists but needs refresh after checkpoint-history fix; layout model is untrained |
| `experiments/` | Reproducible configurations and measured results | Result directory exists; new experiments are added with evidence |
| `scripts/` | Environment inspection, dataset audit, demo, benchmarks, and packaging commands | Environment/storage inspection, synthetic samples, dataset audit, visual evaluation, and packaging scripts exist |
| `src/sketchforge/` | Desktop application and local engineering workflows | Implemented areas listed below; later-phase packages are reserved |
| `tests/` | Unit, integration, end-to-end, fixtures, and evaluation assets | Unit/integration/end-to-end tests and edit benchmark exist |
| `output/` | Generated projects, renders, reports, and logs | Runtime output; ignored by Git |

## Implemented Python areas

- `application/`, `ui/`, `domain/`, `design_ir/`, `vision/`, `layout/`, `rendering/`, and `editor/` implement the desktop workflow, structured design, image pipeline, editable rendering, and editing commands.
- `evaluation/`, `repair/`, and `orchestration/` implement measurement, bounded repairs, and workflow control.
- `storage/`, `utilities/`, and `datasets/synthetic_generator.py` provide local project storage, common utilities, and original synthetic sketches.
- `integrations/` contains the provider contract and isolated Nebius/NVIDIA integrations. Network calls remain disabled unless configured and consented to.
- `assist/` contains natural-language edit planning and validation.
- `generation/` implements full application generation: `generation/frontend/` (React+TS, HTML/CSS component, page, and style generators), focused backend generators in `generation/backend/`, and packaged text templates in `generation/templates/` for reusable project boilerplate.
- `execution/` and `verification/` implement sandboxed execution with strict command allowlists, resource limits, and lint/typecheck/build/test/browser verification runners.
- `models/component_detector/` and `training/` implement the lightweight CNN detector architecture (MobileNet-style FPN-lite) and training loop (dataloader, early stopping, metrics, checkpointing).

## Intentionally planned areas

The following package directories are reserved for upcoming milestones:
- `models/layout_model/`: Compact layout model predicting bounding boxes and flex groupings.
- `retrieval/`: RAG indexing for design guidelines and code snippets.
- Secondary UI dialogs: `layer_panel.py`, `settings_dialog.py`, `training_panel.py`, `dataset_panel.py`.

## Structural choices and extensions

| Specification path | Repository choice | Reason |
|---|---|---|
| `application/commands.py` | Editor command classes remain in `editor/` | Avoids a forwarding-only second command layer |
| `domain/{project,component,layout,interaction,validation}.py` | Own the project, component, layout, interaction, and document validation contracts; shared strict model base and component enum live alongside them | `design_ir/schema.py` and `design_ir/validation.py` remain backwards-compatible import surfaces |
| `layout/hierarchy.py` | Owns containment and reading-order inference; `vision/layout_inference.py` re-exports it | Keeps geometric interpretation with layout rules while preserving the existing vision import |
| `layout/responsive_rules.py` | Reserved until responsive code generation begins | No current workflow consumes responsive rules |
| `orchestration/workflow.py` | Concrete sketch and repair workflows are split into `sketch_workflow.py` and `repair_workflow.py` | Each workflow has separate state transitions |
| `assist/` | Added as a separate package | Natural-language editing is implemented and isolated from core design modules |
| `uv.lock` | Not present | The project does not currently use uv |
| `LICENSE` | Present | Retained as a project-root file; its terms are owned by the project author |

Do not treat reserved directories as implemented features. Track feature progress in `TASKS.md` and update this map as modules move from planned to implemented.
