"""Generate a synthetic dataset for training the component detector.

Produces paired (sketch image, label JSON) files in ``datasets/synthetic/``
using the programmatic sketch generator.  Every image comes with exact
ground-truth bounding boxes and component types.

Usage
-----
    python -I scripts/generate_synthetic_data.py [options]

Options
-------
--out DIR        Output directory (default: datasets/synthetic)
--count N        Number of training images to generate (default: 500)
--seed SEED      Base random seed for reproducibility (default: 1)
--conditions     Comma-separated photo conditions to include
                 (default: clean,shadow,noisy,blur,thin,thick)
--preview N      Save N preview PNG files with GT overlays for inspection

Important: This generates synthetic data only. Results on these images must
not be treated as results on real hand-drawn sketches (see KNOWN_LIMITATIONS.md).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sketchforge.datasets.synthetic_generator import (  # noqa: E402
    ALL_LAYOUTS,
    CONDITIONS,
    render_sketch,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="datasets/synthetic",
                    help="Output directory (default: datasets/synthetic)")
    ap.add_argument("--count", type=int, default=500,
                    help="Number of images to generate (default: 500)")
    ap.add_argument("--seed", type=int, default=1,
                    help="Base random seed (default: 1)")
    ap.add_argument("--conditions", default="clean,shadow,noisy,blur,thin,thick",
                    help="Comma-separated photo conditions to use")
    ap.add_argument("--preview", type=int, default=5,
                    help="Save N images with GT overlays into <out>/previews/")
    args = ap.parse_args()

    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    preview_dir = out / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    layout_names = list(ALL_LAYOUTS.keys())
    cond_names = [c.strip() for c in args.conditions.split(",") if c.strip() in CONDITIONS]
    if not cond_names:
        print("ERROR: no valid conditions specified. Choose from:", list(CONDITIONS.keys()))
        return 1

    rng = random.Random(args.seed)
    manifest = []
    t0 = time.perf_counter()
    n_preview = 0

    print(f"Generating {args.count} synthetic sketches into {out} …")
    print(f"  Layouts:    {layout_names}")
    print(f"  Conditions: {cond_names}")
    print()

    for i in range(args.count):
        layout_name = rng.choice(layout_names)
        cond_name = rng.choice(cond_names)
        seed_i = args.seed + i

        spec = ALL_LAYOUTS[layout_name]()
        image, truth = render_sketch(spec, seed=seed_i, condition=cond_name)

        stem = f"{layout_name}_{cond_name}_{seed_i:06d}"
        img_path = out / f"{stem}.png"
        lbl_path = out / f"{stem}.json"

        cv2.imwrite(str(img_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        lbl_path.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")

        manifest.append({
            "sample_id": stem,
            "layout": layout_name,
            "condition": cond_name,
            "seed": seed_i,
            "image": img_path.name,
            "labels": lbl_path.name,
            "width": image.shape[1],
            "height": image.shape[0],
            "n_components": len(truth["components"]),
        })

        # Save preview with GT overlays
        if n_preview < args.preview:
            vis = image.copy()
            for c in truth["components"]:
                x, y, w, h = [int(v) for v in c["bbox"]]
                cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 180, 0), 2)
                cv2.putText(vis, c["type"][:8], (x + 2, y + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 220), 1)
            cv2.imwrite(str(preview_dir / f"preview_{n_preview:03d}_{stem}.jpg"), vis,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            n_preview += 1

        if (i + 1) % 100 == 0 or (i + 1) == args.count:
            elapsed = time.perf_counter() - t0
            print(f"  {i + 1:5d}/{args.count}  {elapsed:.1f}s  (~{elapsed / (i + 1) * 1000:.0f} ms/image)")

    # Write dataset manifest
    manifest_path = out / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "generator": "scripts/generate_synthetic_data.py",
        "base_seed": args.seed,
        "count": len(manifest),
        "layouts": layout_names,
        "conditions": cond_names,
        "synthetic_only": True,
        "note": (
            "All images are synthetic (see datasets/synthetic_generator.py). "
            "Results on these images must NOT be reported as results on real sketches."
        ),
        "samples": manifest,
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")

    elapsed_total = time.perf_counter() - t0
    print()
    print(f"Done. {len(manifest)} images in {out}")
    print(f"  manifest: {manifest_path.relative_to(ROOT)}")
    print(f"  previews: {preview_dir.relative_to(ROOT)} ({n_preview} files)")
    print(f"  total time: {elapsed_total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
