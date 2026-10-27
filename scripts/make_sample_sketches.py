"""Regenerate the bundled sample sketches.

These are *synthetic* sketches drawn by our own generator (src/sketchforge/datasets/
synthetic_generator.py): wobbly strokes, paper texture, shadows and noise, with known ground truth.
They are not photographs of human drawings, and results on them must not be read as results on real
sketches. Each file is written next to a ``.truth.json`` with the layout's ground-truth boxes.

    .venv/bin/python -I scripts/make_sample_sketches.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sketchforge.datasets.synthetic_generator import ALL_LAYOUTS, render_sketch  # noqa: E402

# (layout, condition, seed): a mix of clean and photo-like captures
SAMPLES = [
    ("login_page", "shadow", 7),
    ("dashboard", "clean", 7),
    ("mobile_form", "noisy", 7),
    ("landing_page", "clean", 7),
    ("settings_page", "shadow", 7),
]


def main() -> int:
    out = ROOT / "assets" / "sample_sketches"
    out.mkdir(parents=True, exist_ok=True)
    for layout, condition, seed in SAMPLES:
        image, truth = render_sketch(ALL_LAYOUTS[layout](), seed=seed, condition=condition)
        stem = f"{layout}_synthetic"
        cv2.imwrite(str(out / f"{stem}.png"), image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        (out / f"{stem}.truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {stem}.png  {image.shape[1]}x{image.shape[0]}  condition={condition} seed={seed}")
    (out / "README.md").write_text(
        "# Sample sketches\n\n"
        "Synthetic sketches produced by `scripts/make_sample_sketches.py` from our own generator. "
        "They imitate pen strokes, paper, shadows and noise but are **not** photographs of human "
        "drawings; use them for the demo and tests only. `*.truth.json` holds each layout's "
        "ground-truth component boxes in sketch pixels.\n\n"
        "To try your own drawing, use *File > Import sketch* (or `sketchforge demo --image PATH`).\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
