"""Detection benchmark on generated sketches with exact ground truth.

    .venv/bin/python -I scripts/evaluate_layout.py [--seeds 11 12 13] [--out experiments/results/detection_benchmark.json]

Reports precision/recall/F1 of component boxes, type accuracy among matched boxes and mean IoU,
split by tuning layouts (the classifier rules were adjusted while looking at these) and held-out
layouts (never looked at during tuning), and by photo condition.

IMPORTANT: every number is about *synthetic* sketches from our own generator. It says nothing about
how the pipeline behaves on real photographs of human drawings; see docs/KNOWN_LIMITATIONS.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sketchforge.datasets.synthetic_generator import CONDITIONS, HELDOUT_LAYOUTS, TUNING_LAYOUTS  # noqa: E402
from sketchforge.evaluation.benchmark_runner import run_benchmark  # noqa: E402

METRICS = ("f1", "precision", "recall", "type_accuracy", "mean_iou", "frame_iou", "mean_ms", "failures", "cases")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[11, 12, 13])
    ap.add_argument("--out", default="experiments/results/detection_benchmark.json")
    args = ap.parse_args()
    started = time.perf_counter()
    report: dict = {"seeds": args.seeds, "conditions": list(CONDITIONS), "synthetic_only": True, "groups": {}}
    for label, layouts in (("tuning_layouts", TUNING_LAYOUTS), ("heldout_layouts", HELDOUT_LAYOUTS)):
        summary = run_benchmark(layouts, list(CONDITIONS), args.seeds)
        overall = summary.aggregate()["all"]
        group = {
            "layouts": sorted(layouts), "overall": {k: overall[k] for k in METRICS if k in overall},
            "by_condition": {k: {m: v[m] for m in METRICS if m in v}
                             for k, v in summary.aggregate(lambda c: c.condition).items()},
            "by_layout": {k: {m: v[m] for m in METRICS if m in v}
                          for k, v in summary.aggregate(lambda c: c.layout).items()},
            "worst_cases": [
                {"layout": c.layout, "condition": c.condition, "seed": c.seed, "f1": round(c.scores.f1, 3),
                 "missed": c.scores.missed_types, "extra": c.scores.extra_types}
                for c in sorted(summary.ok_cases(), key=lambda c: c.scores.f1)[:5]
            ],
        }
        report["groups"][label] = group
        o = group["overall"]
        print(f"{label:16s} cases={int(o['cases']):3d} F1={o['f1']:.3f} P={o['precision']:.3f} R={o['recall']:.3f} "
              f"typeAcc={o['type_accuracy']:.3f} IoU={o['mean_iou']:.3f} fail={int(o['failures'])} "
              f"{o['mean_ms']:.0f} ms/sketch")
        for cond, v in group["by_condition"].items():
            print(f"    {cond:12s} F1={v['f1']:.3f} typeAcc={v['type_accuracy']:.3f} IoU={v['mean_iou']:.3f} fail={int(v['failures'])}")
    report["wall_seconds"] = round(time.perf_counter() - started, 1)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({report['wall_seconds']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
