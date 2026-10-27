# Architecture

SketchForge is a **local-first, single-process** desktop application. The desktop app itself has no
HTTP server, API, microservice, or cloud backend; its modules call each other with typed objects.
The separate project generator can emit Flask/FastAPI REST or Strawberry GraphQL APIs for generated
apps. Long desktop work runs on background threads and reports back through events.

```
┌───────────────────────────────┐
│ ui/  (PySide6 views only)     │  canvas · tree · properties · measure & repair · code
└──────────────┬────────────────┘  Qt signals ◀── ControllerBridge ◀── controller events
               │ method calls
┌──────────────▼────────────────┐
│ application/AppController     │  no Qt types: runs identically under GUI, CLI and tests
│  EventBus · TaskManager       │  project open/save/export, edit, undo, evaluate, repair
└──────────────┬────────────────┘
               │ in-process calls
┌──────────────▼────────────────┐
│ orchestration/                │  step registry · workflow runner · budgets · stopping rules
│  sketch_workflow, repair_workflow
└───┬────────┬────────┬─────────┘
    ▼        ▼        ▼
 vision/  layout/  evaluation/ ─▶ repair/ ─▶ editor/ ─▶ design_ir/ ◀── rendering/
```

## The contract: Design IR

`design_ir/` is the only shared representation. Vision output is converted into it once; after
that the renderer, editor, evaluator and repair engine all read and write the *same* document.
No module keeps a private model of the design. Format: [DESIGN_IR_SPEC.md](DESIGN_IR_SPEC.md).

## The closed loop

```
evaluate ──▶ pick issue ──▶ diagnose cause ──▶ candidate patches (rules, ordered)
   ▲                                              │
   │                              trial-apply ◀───┘   (snapshot + hash taken first)
   │                                   │
   │            re-render + re-evaluate (same code path as the UI uses)
   │                                   │
   └── accept ◀── regression check ────┴──▶ reject ──▶ exact rollback (hash verified)
```

* **Patch** = target component, property, original value, proposed value, reason, expected
  improvement (`repair/patch.py`). Patches become ordinary undoable commands.
* **Accepted only if** the target issue's measure improves by at least `min_target_improvement`,
  *and* no new issue appears (a regrouped issue that continues an old one is matched, not counted
  as new), *and* no other issue grows, *and* fidelity to the sketch does not drop more than
  0.02 mean IoU or 2 px mean position error (`repair/regression_check.py`).
* **Hard limits** (`orchestration/`): 3 attempts per failure (only real attempts count),
  6 iterations, 20 s budget, a no-progress window of 4 attempts, cooperative cancellation.
* **Honest outcomes**: `IMPROVED`, `REGRESSED`, `NO_MEASURABLE_DIFFERENCE`, `UNABLE_TO_VERIFY`. A
  fault that no rule can fix is reported as remaining, never papered over (there is a test for it).
* **Rules are deterministic.** No model assists the repair yet; a model-driven strategy will be
  added only if it beats the rules on the repair matrix.

## Threads and consistency

`TaskManager` runs work on a small thread pool (`import`, `repair`). A repair works on a **copy**
of the document and is applied back as one `ReplaceDocumentCommand` (a single undo step) under the
controller's lock; if the user edited meanwhile (revision changed) the result is **refused**, not
merged. The UI receives controller events as Qt signals on the GUI thread (`ui/bridge.py`).

## Rendering

One deterministic path per format from the same document: SVG (also the canvas preview, via
QtSvg), nested semantic HTML with parent-relative CSS, and a Pillow raster snapshot used for
pixel/SSIM metrics. Text width is an *estimate* shared by builder, evaluator and renderers
(`domain/typography.py`), not a font engine, so "text fits" is a model statement, not a pixel one.

## Shared layout rules

Alignment families (stack: left/centre/right; row: top/centre/bottom), snap radius, tolerances and
repeated-group (≥ 3 similar siblings) pitch fitting live in `layout/grouping.py` and are used by the
IR builder, the evaluator **and** the repair rules, so "aligned" means the same thing everywhere.

## External services

None are used by Milestone 1. When the NVIDIA/Nebius integration is added it will live only under
`integrations/`, behind a typed provider interface, disabled by default, with a consent gate
before any user content leaves the machine, and a local fallback. It is an *outbound client* of a
provider, not an API of ours. See [NEBIUS_NVIDIA_INTEGRATION.md](NEBIUS_NVIDIA_INTEGRATION.md).

## Decisions

[0001 desktop architecture](decisions/0001-desktop-architecture.md) ·
[0002 Design IR](decisions/0002-design-ir.md) ·
[0003 model training strategy](decisions/0003-model-training-strategy.md)
