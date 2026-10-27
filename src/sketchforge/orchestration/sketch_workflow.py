"""The sketch -> editable design -> measured -> repaired workflow (milestone 1).

    load_image -> analyze -> build_design -> validate -> evaluate
               -> inject (optional) -> repair -> save_outputs

Each step reads and writes ``state.context``. The application controller runs the first five for an
import, and the CLI demo runs all of them. Everything here is an in-process function call.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

import cv2
import numpy as np

from sketchforge import __version__
from sketchforge.bootstrap import AppConfig, load_config
from sketchforge.design_ir.serialization import document_hash, save_document, to_json
from sketchforge.design_ir.validation import validate_document
from sketchforge.editor.undo_redo import UndoStack
from sketchforge.evaluation.evaluator import evaluate_document
from sketchforge.exceptions import WorkflowError
from sketchforge.layout.design_refinement import build_document
from sketchforge.orchestration.repair_workflow import run_repair
from sketchforge.orchestration.step_registry import StepRegistry
from sketchforge.orchestration.workflow import ProgressFn, Workflow
from sketchforge.orchestration.workflow_state import WorkflowState
from sketchforge.rendering.renderer import render_all
from sketchforge.repair.error_injection import inject
from sketchforge.utilities.paths import atomic_write_bytes, atomic_write_text, ensure_dir
from sketchforge.vision.image_loader import load_image
from sketchforge.vision.pipeline import analyze
from sketchforge.vision.visualization import draw_detections

REGISTRY = StepRegistry()
IMPORT_STEPS = ["load_image", "analyze", "build_design", "validate", "evaluate"]
DEMO_STEPS = [*IMPORT_STEPS, "inject", "repair", "save_outputs"]


def _cfg(state: WorkflowState) -> AppConfig:
    return state.context.setdefault("config", load_config())


@REGISTRY.register("load_image")
def load_image_step(state: WorkflowState) -> str:
    cfg = _cfg(state)
    loaded = load_image(state.require("path"), cfg.vision)
    state.context["loaded"] = loaded
    return f"{loaded.name} {loaded.width}x{loaded.height} sha256={loaded.sha256[:12]}"


@REGISTRY.register("analyze")
def analyze_step(state: WorkflowState) -> str:
    cfg = _cfg(state)
    result = analyze(state.require("loaded"), cfg.vision)
    state.context["vision"] = result
    kinds: dict[str, int] = {}
    for d in result.detections:
        kinds[d.type] = kinds.get(d.type, 0) + 1
    return (f"threshold={result.preprocessed.variant} stroke={result.preprocessed.stroke_width:.1f}px "
            f"frame={result.proposals.frame.source} detections={len(result.detections)} {kinds}")


@REGISTRY.register("build_design")
def build_design_step(state: WorkflowState) -> str:
    cfg = _cfg(state)
    vision = state.require("vision")
    doc, report = build_document(vision, cfg.constraints, name=state.context.get("name"))
    state.context.update(document=doc, build_report=report, stack=UndoStack(doc),
                         initial_design_json=to_json(doc))
    return (f"{len(doc.components) - 1} components; snapped {report.alignment_moves} alignment, "
            f"{report.spacing_moves} spacing, clamped {len(report.clamped)}")


@REGISTRY.register("validate")
def validate_step(state: WorkflowState) -> str:
    report = validate_document(state.require("document"))
    report.raise_if_invalid()
    state.context["validation"] = report
    return f"valid; {len(report.warnings)} warning(s)"


@REGISTRY.register("evaluate")
def evaluate_step(state: WorkflowState) -> str:
    cfg = _cfg(state)
    ev = evaluate_document(state.require("document"), cfg.constraints)
    state.context["evaluation"] = ev
    return f"{int(ev.metrics['issues_total'])} issue(s): {sorted({i.code for i in ev.issues}) or 'none'}"


@REGISTRY.register("inject")
def inject_step(state: WorkflowState) -> str:
    kind = state.context.get("inject")
    if not kind:
        return "skipped (no fault requested)"
    cfg = _cfg(state)
    doc, stack = state.require("document"), state.require("stack")
    record = inject(doc, kind, stack, cfg.constraints)
    state.context["injection"] = record
    ev = evaluate_document(doc, cfg.constraints)
    state.context["evaluation"] = ev
    found = [i.key for i in ev.issues if i.code == record.expected_code]
    if not found:
        raise WorkflowError(f"injected {kind!r} but the evaluator did not report {record.expected_code}")
    return f"{record.description}; evaluator reports {', '.join(found)}"


@REGISTRY.register("repair")
def repair_step(state: WorkflowState) -> str:
    if not state.context.get("repair", True):
        return "skipped"
    cfg = _cfg(state)
    doc, stack = state.require("document"), state.require("stack")
    injection = state.context.get("injection")
    state.context["rendered_before_repair"] = render_all(doc)
    state.context["design_json_before_repair"] = to_json(doc)
    report = run_repair(
        doc, constraints=cfg.constraints, policy=cfg.regression, limits=cfg.workflow, stack=stack,
        injection=injection.to_dict() if injection else None, cancelled=lambda: state.cancelled,
    )
    state.context["report"] = report
    state.context["evaluation"] = report.final
    return report.headline()


@REGISTRY.register("save_outputs")
def save_outputs_step(state: WorkflowState) -> str:
    out_dir = state.context.get("output_dir")
    if not out_dir:
        return "skipped (no output directory)"
    out = ensure_dir(out_dir)
    doc = state.require("document")
    vision = state.require("vision")
    artifacts: dict[str, str] = {}

    def note(label: str, path: Path) -> None:
        artifacts[label] = str(path.relative_to(out)) if out in path.parents else str(path)

    atomic_write_text(out / "design_initial.json", state.require("initial_design_json"))
    note("design_initial", out / "design_initial.json")
    if "design_json_before_repair" in state.context:
        atomic_write_text(out / "design_before_repair.json", state.context["design_json_before_repair"])
        note("design_before_repair", out / "design_before_repair.json")
    note("design_final", save_document(doc, out / "design_final.json"))

    if "rendered_before_repair" in state.context:
        for kind, p in state.context["rendered_before_repair"].save(out / "renders", "before_repair").items():
            note(f"render_before_{kind}", p)
    for kind, p in render_all(doc).save(out / "renders", "after_repair").items():
        note(f"render_after_{kind}", p)

    ok, buf = cv2.imencode(".png", draw_detections(vision.normalized.color, vision.detections, vision.proposals.frame))
    if ok:
        note("diagnostic_detections", atomic_write_bytes(ensure_dir(out / "diagnostics") / "detections.png", buf.tobytes()))
    ok, buf = cv2.imencode(".png", vision.preprocessed.ink)
    if ok:
        note("diagnostic_ink_mask", atomic_write_bytes(out / "diagnostics" / "ink_mask.png", buf.tobytes()))

    report = state.context.get("report")
    if report is not None:
        for kind, p in report.save(out / "reports", "repair_report").items():
            note(f"report_{kind}", p)

    summary = {
        "sketchforge_version": __version__,
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "source": {"name": state.require("loaded").name, "sha256": state.require("loaded").sha256},
        "document": {"components": len(doc.components) - 1, "hash": document_hash(doc),
                     "page": [doc.page.width, doc.page.height]},
        "outcome": report.outcome.value if report else None,
        "headline": report.headline() if report else None,
        "injection": state.context["injection"].to_dict() if "injection" in state.context else None,
        "steps": state.history.to_list(),
        "artifacts": artifacts,
        "network": "none: the whole workflow ran locally and made no network requests",
    }
    atomic_write_text(out / "summary.json", json.dumps(summary, indent=2, sort_keys=True))
    state.context["artifacts"] = {k: str(out / v) if not Path(v).is_absolute() else v for k, v in artifacts.items()}
    state.context["summary"] = summary
    return f"wrote {len(artifacts) + 1} files to {out}"


def build_workflow(order: list[str]) -> Workflow:
    return Workflow(REGISTRY, order)


def run_sketch_workflow(
    path: str | Path,
    *,
    config: AppConfig | None = None,
    steps: list[str] | None = None,
    inject_kind: str | None = None,
    repair: bool = True,
    output_dir: str | Path | None = None,
    name: str | None = None,
    on_progress: ProgressFn | None = None,
    state: WorkflowState | None = None,
) -> WorkflowState:
    state = state or WorkflowState()
    state.context.update(path=str(path), config=config or load_config(), inject=inject_kind, repair=repair,
                         output_dir=str(output_dir) if output_dir else None, name=name)
    return build_workflow(steps or (DEMO_STEPS if output_dir or inject_kind else IMPORT_STEPS)).run(
        state, on_progress)
