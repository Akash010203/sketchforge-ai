"""Reproducible detection benchmark over generated sketches with exact ground truth.

Every number it produces is about *synthetic* sketches (see datasets/synthetic_generator.py).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sketchforge.bootstrap import VisionConfig
from sketchforge.datasets.synthetic_generator import (
    ALL_LAYOUTS,
    CONDITIONS,
    SketchSpec,
    render_sketch,
)
from sketchforge.evaluation.component_metrics import (
    BoxItem,
    DetectionScores,
    box_iou,
    score_detection,
)
from sketchforge.exceptions import SketchForgeError
from sketchforge.vision.image_loader import from_array
from sketchforge.vision.pipeline import VisionResult, analyze


@dataclass
class CaseResult:
    layout: str
    condition: str
    seed: int
    scores: DetectionScores | None
    frame_iou: float = 0.0
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class BenchmarkSummary:
    cases: list[CaseResult] = field(default_factory=list)

    def ok_cases(self) -> list[CaseResult]:
        return [c for c in self.cases if c.scores is not None]

    def aggregate(self, key: Callable[[CaseResult], str] | None = None) -> dict[str, dict[str, float]]:
        groups: dict[str, list[CaseResult]] = {}
        for c in self.cases:
            groups.setdefault(key(c) if key else "all", []).append(c)
        out: dict[str, dict[str, float]] = {}
        for name, items in sorted(groups.items()):
            ok = [c for c in items if c.scores is not None]
            def mean(f: Callable[[CaseResult], float], ok: list[CaseResult] = ok) -> float:
                return round(statistics.fmean(f(c) for c in ok), 4) if ok else 0.0
            out[name] = {
                "cases": len(items),
                "failures": len(items) - len(ok),
                "precision": mean(lambda c: c.scores.precision),
                "recall": mean(lambda c: c.scores.recall),
                "f1": mean(lambda c: c.scores.f1),
                "type_accuracy": mean(lambda c: c.scores.type_accuracy),
                "mean_iou": mean(lambda c: c.scores.mean_iou),
                "frame_iou": mean(lambda c: c.frame_iou),
                "mean_ms": mean(lambda c: c.elapsed_ms),
            }
        return out


def result_to_items(result: VisionResult) -> list[BoxItem]:
    return [BoxItem(d.type, result.source_box(d.bbox)) for d in result.detections]


def gt_to_items(gt: dict) -> list[BoxItem]:
    return [BoxItem(c["type"], tuple(c["bbox"])) for c in gt["components"] if c["type"] != "page"]


def gt_frame(gt: dict) -> tuple[float, float, float, float] | None:
    for c in gt["components"]:
        if c["type"] == "page":
            return tuple(c["bbox"])
    return None


def run_case(
    spec: SketchSpec,
    condition: str,
    seed: int,
    cfg: VisionConfig | None = None,
    **analyze_kwargs,
) -> CaseResult:
    import time

    img, gt = render_sketch(spec, seed=seed, condition=condition)
    t0 = time.perf_counter()
    try:
        result = analyze(from_array(img), cfg, **analyze_kwargs)
    except SketchForgeError as exc:
        return CaseResult(spec.name, condition, seed, None, error=str(exc))
    elapsed = (time.perf_counter() - t0) * 1000
    scores = score_detection(result_to_items(result), gt_to_items(gt))
    frame = gt_frame(gt)
    frame_iou = box_iou(result.source_box(result.proposals.frame.bbox), frame) if frame else 0.0
    return CaseResult(spec.name, condition, seed, scores, frame_iou, elapsed_ms=elapsed)


def run_benchmark(
    layouts: Iterable[str],
    conditions: Iterable[str],
    seeds: Iterable[int],
    cfg: VisionConfig | None = None,
    **analyze_kwargs,
) -> BenchmarkSummary:
    summary = BenchmarkSummary()
    seeds = list(seeds)
    conditions = list(conditions)
    for layout in layouts:
        spec = ALL_LAYOUTS[layout]()
        for condition in conditions:
            if condition not in CONDITIONS:
                raise KeyError(f"unknown condition {condition!r}")
            for seed in seeds:
                summary.cases.append(run_case(spec, condition, seed, cfg, **analyze_kwargs))
    return summary
