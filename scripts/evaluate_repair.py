#!/usr/bin/env python
"""Closed-loop repair benchmark: layouts x photo conditions x seeds x injected fault kinds.

For every generated sketch the vision pipeline runs once; for every fault kind a fresh design is
built from it, one fault is injected, and the bounded repair loop runs. Reported per cell:

  detected    the evaluator reported the injected fault's issue code
  repaired    no issues remain afterwards
  clean       repaired with zero rejected attempts
  regressed   the final document has MORE issues than right after injection (must be 0)

Synthetic sketches only: this measures the repair engine, not handwriting robustness.

Usage:  python scripts/evaluate_repair.py [--conditions clean shadow ...] [--seeds 11 12]
                                          [--out experiments/results/repair_matrix.json]
                                          [--model-provider nebius]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sketchforge.bootstrap import load_config  # noqa: E402
from sketchforge.datasets.synthetic_generator import ALL_LAYOUTS, CONDITIONS, render_sketch  # noqa: E402
from sketchforge.editor.undo_redo import UndoStack  # noqa: E402
from sketchforge.evaluation.evaluator import evaluate_document  # noqa: E402
from sketchforge.exceptions import RepairError, SketchForgeError  # noqa: E402
from sketchforge.layout.design_refinement import build_document  # noqa: E402
from sketchforge.orchestration.repair_workflow import run_repair  # noqa: E402
from sketchforge.repair.error_injection import KINDS, inject  # noqa: E402
from sketchforge.vision.image_loader import from_array  # noqa: E402
from sketchforge.vision.pipeline import analyze  # noqa: E402



def _build_provider(name):
    """Return a ModelProvider for *name*, or None if name is None."""
    if name is None:
        return None
    if name == "nebius":
        try:
            from sketchforge.integrations.nebius import ConsentGate, NebiusClient, load_nebius_config
            cfg = load_nebius_config(overrides={"enabled": True})
            consent = ConsentGate()
            consent.acknowledge()
            return NebiusClient(cfg, consent=consent)
        except Exception as exc:  # noqa: BLE001
            import sys as _sys
            print(f"Cannot initialise Nebius provider: {exc}", file=_sys.stderr)
            print("Set NEBIUS_API_KEY and ensure the nebius integration is configured.", file=_sys.stderr)
            raise SystemExit(1) from exc
    import sys as _sys
    print(f"Unknown model provider: {name!r}. Supported values: nebius", file=_sys.stderr)
    raise SystemExit(1)

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layouts", nargs="+", default=sorted(ALL_LAYOUTS))
    ap.add_argument("--conditions", nargs="+", default=["clean", "shadow", "blur", "noisy", "thin"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[11, 12])
    ap.add_argument("--kinds", nargs="+", default=list(KINDS))
    ap.add_argument("--out", default="experiments/results/repair_matrix.json")
    ap.add_argument(
        "--model-provider",
        metavar="NAME",
        default=None,
        help="Enable model-guided repair fallback. Supported values: nebius. "
             "Requires the corresponding API key env-var (NEBIUS_API_KEY).",
    )
    args = ap.parse_args()
    unknown = set(args.conditions) - set(CONDITIONS)
    if unknown:
        ap.error(f"unknown conditions: {sorted(unknown)}")

    provider = _build_provider(args.model_provider)

    cfg = load_config()
    rows, skipped = [], []
    t0 = time.perf_counter()
    for layout in args.layouts:
        for cond in args.conditions:
            for seed in args.seeds:
                img, _ = render_sketch(ALL_LAYOUTS[layout](), seed=seed, condition=cond)
                try:
                    vision = analyze(from_array(img), cfg.vision)
                except SketchForgeError as exc:
                    skipped.append({"layout": layout, "condition": cond, "seed": seed, "why": str(exc)})
                    continue
                for kind in args.kinds:
                    doc, _ = build_document(vision, cfg.constraints)
                    baseline = evaluate_document(doc, cfg.constraints)
                    stack = UndoStack(doc)
                    try:
                        rec = inject(doc, kind, stack, cfg.constraints)
                    except RepairError as exc:
                        skipped.append({"layout": layout, "condition": cond, "seed": seed,
                                        "kind": kind, "why": str(exc)})
                        continue
                    injected_ev = evaluate_document(doc, cfg.constraints)
                    report = run_repair(
                        doc, constraints=cfg.constraints, policy=cfg.regression,
                        limits=cfg.workflow, stack=stack, injection=rec.to_dict(),
                        model_provider=provider,
                    )
                    rows.append({
                        "layout": layout, "condition": cond, "seed": seed, "kind": kind,
                        "baseline_issues": len(baseline.issues),
                        "detected": rec.expected_code in {i.code for i in injected_ev.issues},
                        "issues_injected": len(injected_ev.issues), "issues_final": len(report.final.issues),
                        "repaired": not report.final.issues,
                        "clean": not report.final.issues and not report.rejected,
                        "regressed": len(report.final.issues) > len(injected_ev.issues),
                        "accepted": len(report.accepted), "rejected": len(report.rejected),
                        "outcome": report.outcome.value, "stop": report.stop_reason,
                        "left": [i.key for i in report.final.issues],
                        "ms": round(report.duration_ms, 1),
                        "model_provider": args.model_provider,
                    })
    elapsed = time.perf_counter() - t0

    def rate(items, key):
        return round(sum(1 for r in items if r[key]) / len(items), 4) if items else 0.0

    by_kind = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    summary = {
        "cells": len(rows), "skipped": len(skipped),
        "detected": rate(rows, "detected"), "repaired": rate(rows, "repaired"),
        "clean": rate(rows, "clean"), "regressed": rate(rows, "regressed"),
        "median_repair_ms": round(statistics.median(r["ms"] for r in rows), 1) if rows else 0.0,
        "wall_seconds": round(elapsed, 1),
        "model_provider": args.model_provider,
        "by_kind": {k: {"n": len(v), "repaired": rate(v, "repaired"), "clean": rate(v, "clean")}
                    for k, v in sorted(by_kind.items())},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"args": vars(args), "summary": summary, "rows": rows, "skipped": skipped},
                              indent=1, sort_keys=True))
    print(json.dumps(summary, indent=2))
    bad = [r for r in rows if not r["repaired"]]
    for r in bad[:15]:
        print(f"  NOT REPAIRED  {r['layout']}/{r['condition']}/{r['seed']}/{r['kind']}: left {r['left']} ({r['stop']})")
    print(f"wrote {out}")
    return 0 if summary["regressed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
