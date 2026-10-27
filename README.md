# SketchForge AI

> **Autonomous Agentic Engineering Workbench Powered by NVIDIA Nemotron on Nebius Token Factory**  
> *Submitted to the Nebius × NVIDIA Global AI Hackathon — Coding and Agentic Engineering Track*

[![Nebius Token Factory](https://img.shields.io/badge/Platform-Nebius%20Token%20Factory-blue)](https://tokenfactory.nebius.com/)
[![NVIDIA Nemotron](https://img.shields.io/badge/Models-NVIDIA%20Nemotron-76B900?logo=nvidia)](https://developer.nvidia.com/nemotron)
[![Tavily AI Search](https://img.shields.io/badge/Web%20Research-Tavily%20AI-6366f1)](https://tavily.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![Tests: 398 Passed](https://img.shields.io/badge/Tests-398%20Passed-brightgreen)](tests/)

---

## 🌟 Executive Overview

**SketchForge AI** is an autonomous agentic engineering workbench that transforms hand-drawn sketches, wireframes, and whiteboard diagrams into **verified, runnable, full-stack web applications**.

Rather than relying on one-shot code generation that often hallucinates layouts or breaks at runtime, SketchForge operates as a **disciplined, closed-loop engineering system**:
`INSPECT → DESIGN → IMPLEMENT → TEST → MEASURE → DIAGNOSE → IMPROVE → VERIFY`.

Built on high-performance open infrastructure through **Nebius Token Factory** and accelerated by **NVIDIA open-source Nemotron models**, SketchForge combines:
1. **Multimodal Visual Perception**: OpenCV 5 geometric contour extraction paired with **NVIDIA Nemotron-3.5-Super-VL**.
2. **Live Web UI & Pattern Research**: **Tavily AI Search** retrieves current design tokens, accessible WCAG color palettes, and component docs before synthesis.
3. **Tiered Nemotron Multi-Model Routing**: Assigns system architecture to **Nemotron-3-Ultra-550b**, high-speed full-stack code synthesis to **Nemotron-3.5-Lightning**, and surgical micro-repairs to **Nemotron-3-Nano-30B**.
4. **Restricted Execution & Runtime Verification**: Executes generated React/HTML and Flask/SQLite code in a sandboxed headless browser (Playwright).
5. **Autonomous Visual Discrepancy Repair**: Evaluates rendered viewport snapshots against the original Design IR, detects misalignment or overflow, and invokes Nemotron-3-Nano for targeted CSS/DOM patching until layout convergence (**74.14% hybrid pass rate**).

---

## 🏗️ System Architecture & Engineering Flow

The entire end-to-end topology connects the authoring workbench, planning engine, perception pipeline, model routing, and verification sandbox:

![SketchForge AI Architecture Flow](assets/architecture_flow.png)

### Architectural Flow Breakdown

1. **Authoring Workbench (`ui/`)**:
   - **Interactive Web Studio** (`src/sketchforge/ui/web_studio.py`): Browser-based workbench with real-time model tier status pills, device preview switcher (Desktop/Tablet/Mobile), Tavily search toggle, and live code export.
   - **PySide6 Desktop Workbench** (`src/sketchforge/ui/main_window.py`): Local-first desktop workbench with interactive design canvas, component tree, property inspector, and undo/redo history.
   - **Application Controller** (`src/sketchforge/application/app_controller.py`): Manages local task orchestration, background jobs, and project state without internal HTTP/REST overhead.

2. **Planning & Orchestration (`orchestration/`, `generation/`)**:
   - **Workflow Orchestrator** (`src/sketchforge/orchestration/hybrid_orchestrator.py`): Coordinates the lifecycle across perception, generation, verification, and repair with budget managers and stopping rules.
   - **AI Project Generator** (`src/sketchforge/generation/ai_generator.py`): Two-stage generation engine combining AppSpec planning and bounded multi-file synthesis.

3. **Sketch Perception Pipeline (`vision/`, `design_ir/`)**:
   - **Safe Image Loader** (`src/sketchforge/vision/image_loader.py`): Validates dimensions, MIME magic bytes, and memory budgets.
   - **OpenCV 5 Vision Pipeline** (`src/sketchforge/vision/pipeline.py`): Adaptive Otsu & Gaussian thresholding, illumination flattening, stroke width analysis, and quadrilateral perspective deskew.
   - **Design IR Compiler** (`src/sketchforge/vision/to_design_ir.py`): Converts visual detections into a typed, canonical `DesignDocument` AST (`src/sketchforge/design_ir/schema.py`).

4. **Model Integrations & Routing (`agent/`, `integrations/`)**:
   - **Tiered Model Router** (`src/sketchforge/agent/model_router.py`): Selects the optimal NVIDIA Nemotron model on Nebius Token Factory based on cognitive task complexity.
   - **Nebius Client** (`src/sketchforge/integrations/nebius/client.py`): High-throughput OpenAI-compatible client with retry policies, token tracking, and multimodal image support.
   - **Tavily Researcher** (`src/sketchforge/integrations/tavily/client.py`): Performs pre-synthesis web research to ground prompts in real-world design systems.

5. **Execution, Verification & Self-Repair (`execution/`, `verification/`, `repair/`)**:
   - **Restricted Sandbox Runtime** (`src/sketchforge/execution/sandbox.py`): Runs generated Flask and Vite processes with strict command policies and timeout limits.
   - **Playwright Browser Runner** (`src/sketchforge/verification/browser_runner.py`): Launches headless Chromium, loads the preview, and captures pixel-accurate viewport snapshots.
   - **Visual Discrepancy Evaluator** (`src/sketchforge/verification/discrepancy_repair.py`): Measures IoU, centroid Euclidean distance, and element clipping against the source Design IR.
   - **Targeted Self-Repair Loop**: Automatically generates minimal CSS/DOM diffs with Nemotron-3-Nano, re-renders, and verifies layout improvement until convergence.

---

## ⚡ Tiered NVIDIA Nemotron Routing (Why Multi-Model Matters)

In accordance with hackathon guidelines, SketchForge does not use a single monolithic model for all tasks. Instead, it routes workloads dynamically to optimize reasoning depth, latency, and credit consumption:

| Role | NVIDIA Nemotron Model | Nebius Endpoint | Responsibilities & Design Rationale |
|---|---|---|---|
| **System Architecture & Planning** | `nvidia/Nemotron-3-Ultra-550b-a55b` | Nebius Token Factory | Maximum reasoning capacity for defining relational SQLite schemas, foreign key constraints, REST API contracts, and AppSpec JSON (Stage 1). |
| **Full-Stack Code Synthesis** | `nvidia/Nemotron-3_5-Lightning` | Nebius Token Factory | Sub-second latency (~610 ms), 1M token context window, and high instruction adherence for generating React/TS components, CSS styling, and Flask endpoints (Stage 2). |
| **Surgical Discrepancy Repair** | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Nebius Token Factory | Ultra-low latency and credit efficiency for generating targeted 5-to-10 line CSS/DOM diffs during the closed-loop verification cycle. |
| **Multimodal Visual Analysis** | `nvidia/Nemotron-3.5-Super-VL` | Nebius Token Factory | Direct base64 image ingestion with 1M context for zero-shot semantic layout critique, complementing OpenCV geometric contour extraction. |

---

## 🔍 Live Web Research with Tavily AI Search 

SketchForge integrates **Tavily Search API** (`src/sketchforge/integrations/tavily/client.py`) to give the coding agent live, grounded web awareness:
- **Design Tokens & Icons**: Fetches modern Lucide icon names, Tailwind CSS color variables, and fluid typography scales.
- **Accessibility (WCAG AA)**: Queries contrast requirements (>= 4.5:1) and semantic HTML5 standards.
- **Modern Component Patterns**: Injects verified REST route structures and SQLite DDL best practices into the Nemotron prompt context.

*Documentation: See [`docs/TAVILY_INTEGRATION.md`](docs/TAVILY_INTEGRATION.md) for technical design and prompt injection traces.*

---

## 🧩 In-Depth Subsystem Breakdown

### 1. Computer Vision & Layout Perception Engine (`sketchforge/vision/`)
- **Safe Preprocessing**: Performs 40x40 illumination flattening to eliminate paper shadows, glare, and background gradients.
- **Perspective Correction (`vision/perspective.py`)**: 4-point quadrilateral warp to deskew tilted smartphone photos of sketches.
- **Contour Hierarchy**: Evaluates nested contours to detect parent-child container relationships (e.g. inputs inside a card, cards inside a page).
- **Handwriting OCR (`vision/handwriting_ocr.py`)**: CRNN (CNN + BiLSTM + CTC) model to transcribe handwritten button labels and headings into clean digital text.

### 2. Canonical Design Intermediate Representation (`sketchforge/design_ir/`)
- Central source of truth (`design_ir/schema.py`) representing:
  - Component hierarchy tree with stable UUIDs.
  - Geometry: normalized bounding boxes, 8px grid snapping, padding, and margins.
  - Visual tokens: colors, typography scale, border radiuses, and shadow depths.
  - Validation: Pydantic schema validation, versioning, migrations, and deterministic serialization.

### 3. Local Hybrid RAG Retrieval Subsystem (`sketchforge/retrieval/`)
- **BM25 Lexical Index (`retrieval/lexical_index.py`)**: Sub-millisecond keyword lookup over standard component patterns.
- **Vector Index (`retrieval/vector_index.py`)**: Feature-hashed vector index with cosine similarity.
- **Reciprocal Rank Fusion (`retrieval/result_fusion.py`)**: Merges lexical and vector ranking to retrieve optimal boilerplate components offline without external vector databases.

### 4. From-Scratch Model Training & Dataset Pipeline (`sketchforge/training/`, `sketchforge/datasets/`)
- **Custom Component Detector CNN (`models/component_detector/`)**: Compact multi-scale feature pyramid network trained from random initialization.
- **Dataset Streaming Adapters (`datasets/source_adapters.py`)**: Built-in loaders for WebSight, Teklia IAM, Sketch2Diagram, and CommitPackFT with strict safety caps to prevent disk exhaustion.
- **Synthetic Data Generator (`datasets/synthetic_generator.py`)**: Generates paired synthetic sketch images with line jitter, noise, shadows, and ground-truth bounding boxes.
- **Training Infrastructure (`training/trainer.py`)**: Early stopping, reproducible random seeds, GPU auto-detection, and checkpoint managers (`checkpoints/`).

### 5. Full-Stack Project Generation (`sketchforge/generation/`)
- **Frontend Generator (`generation/frontend/`)**: Generates React 18 + TypeScript + Vite components, or pure semantic HTML5/CSS3.
- **Backend Generator (`generation/backend/`)**: Generates Python Flask REST APIs, SQLite DDL schemas, CRUD route handlers, dataclass ORM models, and automated test suites.
- **Deterministic Templates (`generation/templates/`)**: Offline fallback templates ensuring the workbench always yields a working project even without internet connectivity.

### 6. Restricted Execution & Closed-Loop Visual Repair (`sketchforge/verification/`, `sketchforge/repair/`)
- **Sandboxed Execution (`execution/sandbox.py`)**: Runs preview servers under controlled process isolation with execution time budgets.
- **Visual Discrepancy Evaluator (`verification/discrepancy_repair.py`)**: Compares Playwright browser viewport captures against source Design IR. Calculates IoU overlap and centroid drift.
- **Repair Engine (`repair/repair_planner.py`)**: Formulates structured defect diagnosis (`OVERFLOW_PARENT`, `MISALIGNMENT`, `LOW_CONTRAST`), creates minimal undoable patches with Nemotron-3-Nano, and verifies regression before accepting changes.

---

## 📊 Empirical Benchmarks & Verification Results

### 1. Three-Arm Visual Edit Benchmark (`experiments/results/three_arm_benchmark.json`)
Evaluated across 58 machine-verified UI transformation tasks comparing local rules against Nemotron-assisted workflows:

| Benchmark Arm | Description | Pass Rate | Key Finding |
|---|---|---|---|
| **Arm 1: Local Baseline** | Pure deterministic rule-based parser | **58.62%** (34/58) | Fast (9 ms) but limited to strict pattern matches |
| **Arm 2: Pure Model** | Raw Nemotron translation without verification | **15.52%** (9/58) | Hallucinates invalid layout coordinates without guardrails |
| **Arm 3: Hybrid Closed-Loop** | **Nemotron + Local Verification + Auto-Repair** | **74.14%** (43/58) | **+15.52% boost** over local baseline; auto-repairs 13 complex defects |

### 2. Live Nebius Token Factory Probe (`experiments/results/live_nebius_benchmark.json`)
```json
{
  "provider": "nebius",
  "endpoint": "https://api.tokenfactory.nebius.com/v1/",
  "selected_model": "nvidia/Nemotron-3_5-Lightning",
  "latency_ms": 610.4,
  "prompt_tokens": 23,
  "completion_tokens": 96,
  "status": "verified"
}
```

### 3. Automated Test Suite
- **398 total tests** across unit, integration, and end-to-end suites:
  - 288 Unit tests (`tests/unit/`): Vision, Design IR, editor, metrics, repair, model proposer.
  - 45 Generation pipeline tests (`tests/test_generation_pipeline.py`).
  - 32 Nebius integration tests (`tests/integration/test_nebius_integration.py`).
  - End-to-end generated project execution tests (`tests/end_to_end/`).

---

## 🚀 Quickstart Guide

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/Akash010203/sketchforge-ai.git
cd sketchforge-ai

# Create virtual environment
python -m venv .venv

# Activate environment:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e ".[dev]"
```

### 2. Configure Credentials

Create a `.env` file in the root directory:
```env
NEBIUS_API_KEY=your_nebius_token_factory_key
TAVILY_API_KEY=your_tavily_api_key_optional
```

### 3. Verify Live Nebius Connection

```bash
python scripts/verify_nebius.py --enable --accept-egress
```

### 4. Launch the Interactive Web Studio

```bash
python -m sketchforge studio
```
Open **`http://127.0.0.1:8000/studio`** in your browser:
- Drag & drop any hand-drawn sketch or wireframe image.
- Watch OpenCV and **Nemotron-3.5-Super-VL** analyze the structure.
- Toggle **Tavily UI Search** for live web pattern retrieval.
- Watch model tier pills switch (`Ultra 550B` planning ➔ `Lightning` synthesizing code).
- Observe the automated Playwright visual discrepancy and self-repair loop in real time.
- Download the final verified full-stack project ZIP.

### 5. Launch the PySide6 Desktop Workbench (Optional GUI)

```bash
python -m sketchforge gui
```
Direct local-first desktop workbench with visual bounding box editor, property inspector, undo/redo stack, and natural-language prompt bar.

### 6. Run the Autonomous Headless Demo

```bash
python -m sketchforge demo
```
Executes the full pipeline headlessly in ~3 seconds: loads a synthetic sketch, extracts Design IR, injects a parent overflow defect, auto-repairs it, and exports renders and markdown reports to `output/demo/`.

---

## ☁️ Nebius Serverless Endpoints & Cloud Deployment

SketchForge includes production-ready deployment configurations for **Nebius AI Cloud**:
- **Container Definition**: [`deploy/nebius/Dockerfile`](deploy/nebius/Dockerfile)
- **Serverless API Handler**: [`deploy/nebius/serverless_handler.py`](deploy/nebius/serverless_handler.py)
- **Background Job YAML**: [`deploy/nebius/nebius_job.yaml`](deploy/nebius/nebius_job.yaml)

Run the containerized microservice:
```bash
docker build -t sketchforge-nebius -f deploy/nebius/Dockerfile .
docker run -p 8080:8080 -e NEBIUS_API_KEY=$NEBIUS_API_KEY sketchforge-nebius
```

---

## 👥 Hackathon Submission Details

- **Event**: Nebius × NVIDIA Global AI Hackathon
- **Track**: **Coding and Agentic Engineering Track**
- **Special Prizes Opt-In**:
  - 🌐 **Best Use of Tavily ($3,000)** — [`docs/TAVILY_INTEGRATION.md`](docs/TAVILY_INTEGRATION.md)
  - 💡 **Most Valuable Feedback ($100 + NVIDIA Swag)** — [`docs/HACKATHON_FEEDBACK.md`](docs/HACKATHON_FEEDBACK.md)
- **Models Used**:
  - `nvidia/Nemotron-3-Ultra-550b-a55b`
  - `nvidia/Nemotron-3_5-Lightning`
  - `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
  - `nvidia/Nemotron-3.5-Super-VL`
- **Core Documentation**:
  - 📖 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Comprehensive architecture specification
  - 📋 [`TASKS.md`](TASKS.md) — Verified milestone task ledger
  - 🎬 [`docs/DEMO_VIDEO_SCRIPT.md`](docs/DEMO_VIDEO_SCRIPT.md) — 3-minute video recording storyboard
  - 🔬 [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) — In-depth technical report

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
