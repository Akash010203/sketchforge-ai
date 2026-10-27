"""Deterministic benchmark for natural-language edit planners.

The Oracle arm applies the hand-authored reference plan (or expected refusal) and checks the
task's postconditions. Planner arms use the same fixture, evaluator and postconditions.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from sketchforge.assist.edit_plan import EditPlan, InvalidPlan, parse_plan, resolve_color, validate_plan
from sketchforge.assist.local_parser import parse_instruction
from sketchforge.assist.model_planner import plan_with_model
from sketchforge.assist.verified_edit import apply_plan, introduced_issues
from sketchforge.bootstrap import load_config
from sketchforge.datasets.synthetic_generator import ALL_LAYOUTS, render_sketch
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import from_dict
from sketchforge.evaluation.evaluator import evaluate_document
from sketchforge.exceptions import SketchForgeError
from sketchforge.layout.design_refinement import build_document
from sketchforge.integrations.provider_interface import ModelProvider
from sketchforge.vision.image_loader import from_array
from sketchforge.vision.pipeline import analyze

Planner = Callable[[str, DesignDocument], EditPlan | None]


def load_tasks(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data.get("tasks"), list):
        raise ValueError("benchmark file must contain a tasks array")
    ids = [task.get("id") for task in data["tasks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark task ids must be unique")
    return data


def build_fixtures(data: dict) -> dict[str, DesignDocument]:
    """Build the named deterministic sketch fixtures once per benchmark run."""
    cfg = load_config()
    spec = data.get("fixture", {})
    seed, condition = int(spec.get("seed", 11)), spec.get("condition", "clean")
    docs = {}
    for name in spec.get("layouts", ()):
        if name not in ALL_LAYOUTS:
            raise ValueError(f"unknown benchmark layout {name!r}")
        image, _ = render_sketch(ALL_LAYOUTS[name](), seed=seed, condition=condition)
        vision = analyze(from_array(image), cfg.vision)
        docs[name], _ = build_document(vision, cfg.constraints)
    return docs


def _matches(doc: DesignDocument, checks: list[dict]) -> tuple[bool, list[str]]:
    errors = []
    for check in checks:
        comp = doc.get(check["id"])
        if comp is None:
            errors.append(f"missing component {check['id']}")
            continue
        for key, expected in check.items():
            if key == "id":
                continue
            actual = {
                "fill": comp.style.fill, "border": comp.style.stroke,
                "text_color": comp.typography.color if comp.typography else None,
                "text": comp.text, "font_size": comp.typography.font_size if comp.typography else None,
                "corner_radius": comp.style.corner_radius,
                "x": comp.bbox.x, "y": comp.bbox.y, "w": comp.bbox.w, "h": comp.bbox.h,
            }.get(key)
            if key == "center_x":
                ok = abs(comp.bbox.cx - doc.page.width / 2) <= 3
            elif key in ("dx", "dy"):
                # Movement checks encode the requested displacement from the fixture.
                initial = _FIXTURE_BOXES.get((doc.document_id, comp.id))
                axis = "x" if key == "dx" else "y"
                delta = getattr(comp.bbox, axis) - initial[axis] if initial is not None else None
                if expected in (">", "<"):
                    ok = delta is not None and (delta > 0 if expected == ">" else delta < 0)
                else:
                    ok = delta is not None and abs(delta - expected) <= 2
            elif expected in (">", "<"):
                initial = _FIXTURE_BOXES.get((doc.document_id, comp.id))
                if initial is not None and key in ("w", "h", "font_size", "corner_radius"):
                    if key == "w" or key == "h":
                        before = initial[key]
                    elif key == "font_size":
                        source = _FIXTURE_STYLES.get((doc.document_id, comp.id), {})
                        before = source.get(key)
                    else:
                        source = _FIXTURE_STYLES.get((doc.document_id, comp.id), {})
                        before = source.get(key)
                    ok = before is not None and (actual > before if expected == ">" else actual < before)
                else:
                    ok = False
            elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
                ok = abs(actual - expected) <= 2
            else:
                if key in ("fill", "border", "text_color"):
                    try:
                        ok = actual == resolve_color(expected)
                    except Exception:
                        ok = str(actual).lower() == str(expected).lower()
                else:
                    ok = str(actual).lower() == str(expected).lower()
            if not ok:
                errors.append(f"{check['id']}.{key}: expected {expected!r}, got {actual!r}")
    return not errors, errors


_FIXTURE_BOXES: dict[tuple[str, str], dict[str, float]] = {}
_FIXTURE_STYLES: dict[tuple[str, str], dict[str, float]] = {}


def _copy_fixture(doc: DesignDocument) -> DesignDocument:
    copied = from_dict(doc.snapshot())
    for component in copied.components:
        _FIXTURE_BOXES[(copied.document_id, component.id)] = component.bbox.model_dump()
        _FIXTURE_STYLES[(copied.document_id, component.id)] = {
            "font_size": component.typography.font_size if component.typography else None,
            "corner_radius": component.style.corner_radius,
        }
    return copied


def _outcome(task: dict, base: DesignDocument, plan: EditPlan | None, *, arm: str,
             constraints, repair: bool) -> dict:
    started = time.perf_counter()
    expected_kind = task["expect"]["kind"]
    if plan is None:
        passed = expected_kind == "refuse"
        return {"task_id": task["id"], "arm": arm, "expected": expected_kind,
                "actual": "refuse", "passed": passed, "errors": [] if passed else ["planner refused an edit task"],
                "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    if expected_kind == "refuse":
        return {"task_id": task["id"], "arm": arm, "expected": expected_kind,
                "actual": "edit", "passed": False, "errors": ["planner edited a refusal task"],
                "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    result = apply_plan(base, plan, constraints=constraints, repair=repair)
    errors = list(result.problems)
    if not result.applied or result.document is None:
        errors.append(f"edit status was {result.status}")
    else:
        ok, check_errors = _matches(result.document, task["expect"].get("checks", []))
        errors.extend(check_errors)
        if task["expect"].get("no_new_issues", False) and result.before and result.final:
            bad, _ = introduced_issues(result.before, result.final)
            if bad:
                errors.append(f"new or worsened evaluator issues: {sorted(bad)}")
    return {"task_id": task["id"], "arm": arm, "expected": expected_kind,
            "actual": result.status, "passed": not errors, "errors": errors,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "repair_patches": len(result.repair.accepted) if result.repair else 0}


def oracle_plan(task: dict, doc: DesignDocument) -> EditPlan | None:
    if task["expect"]["kind"] == "refuse":
        return None
    plan = parse_plan(task["reference"])
    validate_plan(plan, doc)
    return plan


def local_plan(task: dict, doc: DesignDocument) -> EditPlan | None:
    result = parse_instruction(task["instruction"], doc)
    return result.plan


def run_benchmark(data: dict, *, arms: tuple[str, ...] = ("oracle", "local", "hybrid"),
                  docs: dict[str, DesignDocument] | None = None,
                  provider: ModelProvider | None = None) -> dict:
    cfg = load_config()
    docs = docs or build_fixtures(data)
    rows = []
    planners = {"oracle": oracle_plan, "local": local_plan}
    for task in data["tasks"]:
        if task["doc"] not in docs:
            raise ValueError(f"task {task['id']} references unavailable fixture {task['doc']!r}")
        for arm in arms:
            if arm not in (*planners, "hybrid", "model"):
                raise ValueError(f"unknown benchmark arm {arm!r}")
            base = _copy_fixture(docs[task["doc"]])
            try:
                if arm in ("hybrid", "model"):
                    model_result = plan_with_model(provider, base, task["instruction"]) if provider else None
                    parsed = model_result.plan if model_result and model_result.ok else None
                    if arm == "hybrid" and parsed is None:
                        parsed = local_plan(task, base)
                    row = _outcome(task, base, parsed, arm=arm, constraints=cfg.constraints,
                                   repair=arm == "hybrid")
                    row["planner"] = "model" if model_result and model_result.ok else (
                        "local_fallback" if arm == "hybrid" else "model_unavailable")
                    if model_result:
                        row["planner_outcome"] = model_result.kind
                        row["planner_reason"] = model_result.reason
                        row["model_latency_ms"] = round(model_result.latency_ms, 2)
                        row["total_tokens"] = model_result.total_tokens
                        row["model"] = model_result.results[-1].model if model_result.results else None
                else:
                    plan = planners[arm](task, base)
                    row = _outcome(task, base, plan, arm=arm, constraints=cfg.constraints,
                                   repair=False)
            except (InvalidPlan, ValidationError, SketchForgeError, ValueError) as exc:
                row = {"task_id": task["id"], "arm": arm, "expected": task["expect"]["kind"],
                       "actual": "error", "passed": False, "errors": [str(exc)], "duration_ms": 0.0}
            rows.append(row)
    summaries = {}
    for arm in arms:
        subset = [row for row in rows if row["arm"] == arm]
        counts = Counter(row["actual"] for row in subset)
        summaries[arm] = {"tasks": len(subset), "passed": sum(r["passed"] for r in subset),
                          "pass_rate": round(sum(r["passed"] for r in subset) / len(subset), 4) if subset else 0,
                          "outcomes": dict(sorted(counts.items()))}
    return {"version": 1, "fixture": data.get("fixture", {}), "summary": summaries, "rows": rows}
