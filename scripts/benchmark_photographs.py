#!/usr/bin/env python
"""Evaluate detections on manually annotated photographed sketches.

Real-sketch mode
----------------
Pass a manifest JSON (list of records with ``image`` and ``truth`` paths).
Truth files use the synthetic benchmark format (a ``components`` list with
type and pixel bbox).  Paths are relative to the manifest.  Photographs and
annotations are deliberately not bundled; see datasets/README.md for how to
collect them.

Synthetic dry-run mode (--synthetic N)
---------------------------------------
When no manifest is available, pass ``--synthetic N`` to generate *N* synthetic
annotated sketches on-the-fly.  This exercises the complete benchmark pipeline
(detection -> score_detection) without any real photographs, so the infrastructure
can be validated immediately and the numbers serve as a reproducible baseline.

Usage::
    # real photos
    python scripts/benchmark_photographs.py datasets/manifests/photo_bench.json

    # synthetic dry-run (no real photos needed)
    python scripts/benchmark_photographs.py --synthetic 20
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sketchforge.evaluation.benchmark_runner import gt_to_items, result_to_items  # noqa: E402
from sketchforge.evaluation.component_metrics import score_detection  # noqa: E402
from sketchforge.vision.image_loader import load_image  # noqa: E402
from sketchforge.vision.pipeline import analyze  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic generation helpers
# ---------------------------------------------------------------------------

def _generate_synthetic_cases(n: int) -> list[dict]:
    """Generate *n* synthetic annotated sketch images and return benchmark cases.

    Each case is a dict with ``in_memory_image`` (numpy array) and ``gt_dict``
    (the full ground-truth dict returned by ``render_sketch``).
    """
    import random
    from sketchforge.datasets.synthetic_generator import ALL_LAYOUTS, CONDITIONS, render_sketch

    layouts = sorted(ALL_LAYOUTS.keys())
    cond_names = ["clean", "shadow", "noisy", "blur", "thin"]
    cases = []
    rng = random.Random(42)
    for i in range(n):
        layout_name = layouts[i % len(layouts)]
        cond_name = cond_names[i % len(cond_names)]
        seed = rng.randint(1, 9999)
        img, gt_dict = render_sketch(
            ALL_LAYOUTS[layout_name](), seed=seed, condition=cond_name
        )
        cases.append({
            "label": f"synthetic-{layout_name}-{cond_name}-{seed}",
            "in_memory_image": img,
            "gt_dict": gt_dict,
        })
    return cases


def _run_synthetic(n: int, out_path: Path) -> int:
    """Run benchmark on *n* synthetic sketches and write results to *out_path*."""
    try:
        cases = _generate_synthetic_cases(n)
    except ImportError as exc:
        print(f"Cannot generate synthetic sketches: {exc}", file=sys.stderr)
        return 1

    results = []
    for case in cases:
        img = case["in_memory_image"]
        gt_dict = case["gt_dict"]  # full dict: {"components": [...], "layout": ..., ...}
        # Analyse the in-memory image via from_array path
        from sketchforge.vision.image_loader import from_array
        loaded = from_array(img)
        result = analyze(loaded)
        scores = score_detection(result_to_items(result), gt_to_items(gt_dict))
        results.append({
            "image": case["label"],
            "scores": scores.__dict__,
            "perspective_corrected": result.perspective.corrected,
            "notes": result.notes,
        })

    summary = {
        "images": len(results),
        "synthetic": True,
        "mean_f1": round(sum(item["scores"]["f1"] for item in results) / len(results), 4)
        if results else 0.0,
        "mean_type_accuracy": round(
            sum(item["scores"]["type_accuracy"] for item in results) / len(results), 4
        ) if results else 0.0,
        "mean_iou": round(
            sum(item["scores"]["mean_iou"] for item in results) / len(results), 4
        ) if results else 0.0,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "cases": results}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Real-manifest mode
# ---------------------------------------------------------------------------

def _run_manifest(manifest_path: Path, out_path: Path, parser: argparse.ArgumentParser) -> int:
    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        parser.error("manifest must be a non-empty JSON list of image/truth records")
    results = []
    for record in records:
        image_path = manifest_path.parent / record["image"]
        truth_path = manifest_path.parent / record["truth"]
        if not image_path.is_file():
            parser.error(f"image does not exist: {image_path}")
        if not truth_path.is_file():
            parser.error(f"annotation does not exist: {truth_path}")
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        if not isinstance(truth.get("components"), list):
            parser.error(f"annotation needs a components array: {truth_path}")
        result = analyze(load_image(image_path))
        scores = score_detection(result_to_items(result), gt_to_items(truth))
        results.append({
            "image": record["image"],
            "scores": scores.__dict__,
            "perspective_corrected": result.perspective.corrected,
            "notes": result.notes,
        })
    summary = {
        "images": len(results),
        "synthetic": False,
        "mean_f1": round(sum(item["scores"]["f1"] for item in results) / len(results), 4)
        if results else 0.0,
        "mean_type_accuracy": round(
            sum(item["scores"]["type_accuracy"] for item in results) / len(results), 4
        ) if results else 0.0,
        "mean_iou": round(
            sum(item["scores"]["mean_iou"] for item in results) / len(results), 4
        ) if results else 0.0,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "cases": results}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "manifest",
        nargs="?",
        help="JSON list of image/truth path pairs (real-photo mode). "
             "Omit when using --synthetic.",
    )
    parser.add_argument(
        "--synthetic",
        metavar="N",
        type=int,
        default=None,
        help="Dry-run with N synthetic annotated sketches instead of real photos.",
    )
    parser.add_argument(
        "--out",
        default="experiments/results/photo_benchmark.json",
        help="Output path for the results JSON.",
    )
    args = parser.parse_args()
    out_path = Path(args.out)

    if args.synthetic is not None:
        if args.manifest is not None:
            parser.error("--synthetic and a manifest path are mutually exclusive")
        if args.synthetic < 1:
            parser.error("--synthetic N requires N >= 1")
        return _run_synthetic(args.synthetic, out_path)

    if args.manifest is None:
        parser.error("provide a manifest path or use --synthetic N")
    return _run_manifest(Path(args.manifest).resolve(), out_path, parser)


if __name__ == "__main__":
    raise SystemExit(main())
