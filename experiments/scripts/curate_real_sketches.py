"""Curate and validate real-world photographed sketch datasets for model training."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def curate_dataset(source_dir: Path, output_manifest: Path) -> dict:
    """Scan source_dir for photographed sketches, compute checksums, and generate dataset manifest."""
    source_dir = Path(source_dir)
    images = [p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS]
    records = []

    for img_path in sorted(images):
        try:
            from PIL import Image
            with Image.open(img_path) as im:
                width, height = im.size
                mode = im.mode
            hasher = hashlib.sha256()
            hasher.update(img_path.read_bytes())
            checksum = hasher.hexdigest()[:16]

            records.append({
                "id": checksum,
                "relative_path": str(img_path.relative_to(source_dir)),
                "width": width,
                "height": height,
                "mode": mode,
                "has_annotation": (img_path.with_suffix(".json")).exists(),
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping %s: %s", img_path, exc)

    manifest = {
        "dataset_name": "real_photographed_sketches",
        "total_images": len(records),
        "annotated_count": sum(1 for r in records if r["has_annotation"]),
        "records": records,
    }

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Curate real photographed sketches")
    parser.add_argument("--source", type=Path, default=Path("assets/real_sketches"), help="Directory containing photos")
    parser.add_argument("--output", type=Path, default=Path("experiments/configs/real_sketch_manifest.json"), help="Output manifest")
    args = parser.parse_args()
    res = curate_dataset(args.source, args.output)
    print(f"Curated {res['total_images']} photos ({res['annotated_count']} annotated). Manifest written to {args.output}")
