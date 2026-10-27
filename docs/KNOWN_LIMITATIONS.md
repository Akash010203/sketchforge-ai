# Known limitations

Read these before relying on any result. Each entry is something that was observed or is true by
construction, not a hypothetical.

## Evidence

* **Real photographed sketches perform poorly.** The checked-in one-image grid-paper benchmark
  (`experiments/results/current_real_photo.json`) reports F1 **0.0333** and type accuracy
  **0.0000**. It is too small to generalize from, but it is strong evidence that photo sketch
  detection is not production-ready. Synthetic measurements must not be represented as photo
  performance.
* The classifier rules were tuned on three layouts; two other layouts were held out and scored
  slightly differently (type accuracy 0.985 vs 0.946). The held-out set is small (42 sketches).
* Confidence values (`type_scores`) are rule scores, **not calibrated probabilities**.

## Vision

* Perspective correction now attempts to detect and rectify one dominant page quadrilateral.
  This is heuristic and may fail on cluttered scenes, curled pages, weak borders or shadows;
  the photo benchmark remains unrun because no photographed samples/annotations are checked in.
* **Handwriting OCR is optional.** Install `sketchforge[ocr]` and set `SKETCHFORGE_OCR_MODEL` to
  `microsoft/trocr-base-handwritten` (or a local compatible TrOCR model) to recognize candidate
  text lines. The first run may download model weights. Recognition is best-effort: missed or
  unreadable text remains a clearly flagged placeholder (`text_is_inferred = true`); verify OCR
  output before relying on it. OCR is off by default.
* A sketch needs a visible page frame or consistent margins to find the page area; with no drawn
  frame the ink bounding box is used and noted.
* Known confusions: card ↔ container, checkbox ↔ radio when poorly drawn, text ↔ heading (heading
  is decided by relative height), text-line splitting under very thin, very thick or blurred
  strokes (`thin` condition is the weakest: held-out F1 0.915).
* A large squarish ink cluster is classified as image with `heading` close behind (flagged ambiguous).
* Blank or near-blank images raise a clear error rather than returning an empty design.

## Layout, evaluation and repair

* Text fit uses an **estimated** glyph width (± ~10 %), not a font engine.
* Repair rules cover the 10 issue codes through geometric edits only (translate, resize, restyle,
  reduce font size to a floor of 10 px). They cannot fix problems that need new content or a
  redesign; those are reported as remaining.
* Repair success is partly "trial and reject": some candidates (widen, shrink) are tried and rolled
  back by the regression check. This is by design and recorded in the report.
* On drawings whose *baseline* (before any injected fault) already contains detection artefacts
  (e.g. the `settings_page` sketch under `thin` strokes produces several overlapping text boxes),
  the engine can stall: it stops after the no-progress window instead of redesigning. See
  EXPERIMENT_LOG for the matrix failures.
* Injected faults are our own; the matrix measures how well the engine repairs *those*, not
  arbitrary user mistakes.

## Application

* Desktop UI verified on Qt's **offscreen** platform only; no interactive display was available in the
  build environment, so real-window look-and-feel, high-DPI behaviour and platform file dialogs were
  not exercised.
* The canvas supports select, drag-move and a bottom-right resize handle; there is no
  add/delete-component tool, multi-select drag or snapping yet.
* Project files store the design, source sketch, renders and reports, but **not** vision
  detections (re-import regenerates them) or the undo history.
* Only one document is open at a time.

## Generated backend targets

* The project generator can emit SQLite, PostgreSQL, and MySQL schema definitions. PostgreSQL/MySQL
  and SQLAlchemy projects need a matching `DATABASE_URL` and database driver; this workspace does
  not provision or connect to a database server for the generated project.
* SQLAlchemy is the Python ORM path for all three databases. Prisma output includes a schema and
  Prisma CLI migration/client scripts under `backend/`; it does not generate a Python API or CRUD
  implementation. Prisma authentication is not supported.
* Generated Python APIs support Flask REST, FastAPI REST, or Strawberry GraphQL CRUD. GraphQL
  exposes list and create/update/delete operations through GraphQL mutations; REST provides the
  standard CRUD routes. These generated APIs are starter code and still need deployment-specific
  rate limits, logging, monitoring, and operational configuration.
* Optional authentication provides scrypt password hashes, JWT bearer tokens with server-side
  logout revocation, protected CRUD routes, and Google OAuth2 routes for Flask/FastAPI/GraphQL
  projects. Google OAuth requires `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`; set a stable,
  random `AUTH_SECRET` for deployments. The Studio preview supplies a temporary local secret when
  one is not configured. OAuth account linking currently uses verified email as the account key.
* Alembic scaffolding is emitted when selected with SQLAlchemy. Create the first revision and apply
  it with the commands in the generated README. Schema autogeneration must be reviewed before
  applying migrations.

## Currently in progress / remaining items

* **Vision**: Collect and annotate licensed photographed sketches, then run `scripts/benchmark_photographs.py`. The benchmark runner is implemented, but no photograph scores are available until a non-empty local manifest and its image/annotation files are supplied.
* **Models & Training**: A 10-epoch CUDA run was reported on generated synthetic layouts (best validation loss 0.3606 at epoch 5; held-out set is one unseen synthetic template). Workspace inspection found that `checkpoints/component_detector_v1/best.pt` still contains an earlier epoch 5 checkpoint (loss 0.147449), because old checkpoint history was considered during pruning. The manager now starts a fresh history per training run; rerun manually to save the reported run's weights. Detection IoU/mAP are not implemented and remain 0; no real-sketch benefit is established. The layout model has architecture, dataset, and inference code, but no trained checkpoint.
* **Dataset processing**: 1,000 WebSight samples were normalized to PNG/HTML/JSON under `datasets/processed/websight-v02/`. They have no component bounding-box labels and are not detector-training data. DrawnUI source files are absent from this checkout; the processing command is ready for when they are provided.
* **Retrieval**: Hybrid BM25/vector retrieval is local and dependency-free by default. Its default vector representation is feature hashing, which provides token-level similarity rather than pretrained semantic embeddings; a local embedding function can be supplied.
* **Integrations**: Nebius client is implemented and verified against an in-process mock transport; live verification requires running `scripts/verify_nebius.py` with a valid `NEBIUS_API_KEY`. NVIDIA local runtime hooks (`integrations/nvidia/runtime.py`) are pending.
* **Testing & Execution**: TypeScript checking invokes `npx tsc --noEmit` through the command sandbox. Browser smoke tests still rely on a host-installed Playwright CLI, its browser runtime, and a separately running preview server; they are not autonomous in a clean sandbox.
* **Packaging**: `scripts/package_application.py --pyinstaller` builds a single-file Windows GUI executable when run on Windows with `.[ui]` and PyInstaller installed. This checkout has not produced or interactively verified a distributable `.exe`.
* **Application**: The browser Studio is the primary workflow. The PySide desktop workbench remains
  a compatibility interface for local Design IR editing; not every desktop panel has a browser
  equivalent yet. Browser natural-language project revision requires a configured AI provider.

## Hardware & Environment

Verified local workstation environment:
* **OS**: Windows 11 (AMD64)
* **CPU**: 12 logical cores
* **GPU**: NVIDIA GeForce RTX 4050 Laptop GPU (6,141 MiB VRAM, Driver 591.74)
* **PyTorch**: 2.6.0+cu124 with CUDA 12.4 acceleration enabled
* **Storage**: 728.19 GB total, 443.90 GB free (planning budget: 221.95 GB)
* **Training capability**: Full CUDA GPU acceleration is available locally for training compact detectors and layout models.
