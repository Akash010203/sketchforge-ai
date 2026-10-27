# Model Card: SketchForge AI

## 1. Overview

**SketchForge AI** employs a hybrid intelligence architecture that pairs deterministic computer vision (OpenCV 5) with a multi-tiered suite of **NVIDIA Nemotron open-source foundation models** served through **Nebius Token Factory**, alongside an autonomous visual self-repair verification loop.

This model card documents the models, routing decisions, context limits, training provenance, and operational boundaries of all models in SketchForge.

---

## 2. NVIDIA Nemotron Model Suite (Nebius Token Factory)

SketchForge accesses NVIDIA open-source models via Nebius Token Factory's OpenAI-compatible inference API (`https://api.tokenfactory.nebius.com/v1/`). A specialized router (`sketchforge/agent/model_router.py`) directs requests to the optimal model tier based on task complexity and latency constraints:

| Model ID | Architecture / Tier | Context Window | Modality | Role in SketchForge |
|---|---|---|---|---|
| **`nvidia/Nemotron-3-Ultra-550b-a55b`** | High-Reasoning Tier | 1,048,576 tokens | Text → Text | **Stage 1 Architecture & Relational Schema Planning**: System topology, multi-entity SQLite schemas, and REST route specifications. |
| **`nvidia/Nemotron-3_5-Lightning`** | High-Throughput Coder | 1,048,576 tokens | Text → Text | **Stage 2 Full-Stack Code Synthesis**: Generates HTML5, modern CSS, React/TS components, and Flask backend endpoints at sub-second latency (~610 ms). |
| **`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`** | Fast Repair Tier | 262,144 tokens | Text → Text | **Autonomous Visual Discrepancy Repair**: Produces targeted, 5-line CSS/DOM patches in response to Playwright visual discrepancy reports. |
| **`nvidia/Nemotron-3.5-Super-VL`** | Multimodal Vision Tier | 1,048,576 tokens | Text + Image → Text | **Multimodal Sketch Perception**: Interprets raw sketch images directly to provide high-level semantic layout critiques and identify user intent. |
| **`nvidia/nemotron-3-super-120b-a12b`** | Balanced Fallback | 262,144 tokens | Text → Text | Fallback candidate for Stage 1 architecture generation during peak load. |

### Inference Latency & Benchmarks (Verified on Token Factory)
- **Live Completion Latency**: `610.4 ms` (96 completion tokens, 23 prompt tokens on `nvidia/Nemotron-3_5-Lightning`).
- **Endpoint**: `https://api.tokenfactory.nebius.com/v1/chat/completions`.
- **Egress Policy**: All remote calls require explicit session authorization through `ConsentGate`. By default, only structured Design IR JSON summaries are transmitted; raw sketch images are only transmitted when the user explicitly triggers `Nemotron-3.5-Super-VL` multimodal analysis.

---

## 3. Local Computer Vision Engine (OpenCV 5)

Before invoking cloud LLMs, SketchForge processes raw sketch photographs locally on the user's device:

* **Image Preprocessing**:
  * **Illumination Flattening**: 40×40 morphological dilation filter removes non-uniform shadows and glare from smartphone photos.
  * **Thresholding**: Adaptive Gaussian and Otsu thresholding separates ink strokes from paper textures and grid lines.
  * **Perspective Deskew**: 4-point quadrilateral contour detection warps tilted paper angles into axis-aligned coordinate planes.
* **Geometric Feature Extraction**:
  * Hierarchical contour analysis detects parent-child nesting (cards containing inputs, buttons inside forms).
  * `approxPolyDP` polygon approximation identifies geometric bounding boxes `[x, y, w, h]`.
* **Design IR Compilation**:
  * Observations are compiled into a canonical, version-controlled `DesignDocument` AST (`src/sketchforge/design_ir/schema.py`).
  * Enforces an 8px spatial grid, layout snapping, and geometric containment constraints.

---

## 4. Local Trainable Models (PyTorch)

Located under `src/sketchforge/models/`:
* **Component Detector CNN** (`models/component_detector/`):
  * **Architecture**: Compact Multi-Scale Feature Pyramid Network with anchor-based classification heads.
  * **Trained Classes**: `button`, `input`, `card`, `heading`, `text`, `image`, `checkbox`, `divider`.
  * **Training Setup**: 100% scratch initialization (no pretrained weights), cross-entropy + smooth L1 box regression losses.
  * **Hardware**: Verified on NVIDIA GeForce RTX 4050 Laptop GPU (6,140 MiB VRAM).
  * **Checkpoints**: Stored in `checkpoints/` with automated SHA-256 integrity verification.

---

## 5. Intended Use & Safety Guardrails

### Intended Use
* Converting hand-drawn sketches, wireframes, and whiteboard UI designs into verified, full-stack prototypes.
* Closed-loop autonomous visual repair of rendered web applications.

### Out-of-Scope & Limitations
* **Production Deployment without Review**: Generated full-stack applications are intended as functional prototypes and scaffolds; security audits and human code review are recommended before commercial production deployment.
* **Handwriting Deciphering**: Low-contrast, illegible, or cursive handwriting may be marked as placeholder text regions rather than exact semantic strings.
* **Network Independence**: The core desktop workbench (OpenCV detection, Design IR editing, deterministic HTML/CSS rendering, and local rule repairs) functions completely offline without internet or Nebius credentials. Remote Nemotron synthesis requires active Nebius Token Factory access.
