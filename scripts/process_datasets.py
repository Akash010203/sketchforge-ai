"""Convert local source-adapter samples into a normalized processed dataset.

Examples:
    python scripts/process_datasets.py --dataset websight-v02 --max-samples 1000
    python scripts/process_datasets.py --dataset imageclef-drawnui-2021

Output is for inspection/research. This command does not make a dataset license or source-content
rights determination and does not add unlabelled images to detector training data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sketchforge.datasets.source_adapters import get_adapter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--max-samples", type=int, default=1000)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.max_samples < 1:
        parser.error("--max-samples must be positive")
    out = (ROOT / args.out).resolve() if args.out else ROOT / "datasets" / "processed" / args.dataset
    out.mkdir(parents=True, exist_ok=True)
    adapter = get_adapter(args.dataset)
    if not adapter.is_available():
        print(f"No local source data found for {args.dataset}.")
        return 2
    manifest_path = ROOT / "datasets" / "manifests" / "manifest.json"
    dataset_records = json.loads(manifest_path.read_text(encoding="utf-8")).get("datasets", [])
    source_record = next((item for item in dataset_records
                          if item.get("id") == adapter.dataset_id), {})

    import cv2
    import numpy as np
    records = []
    seen = set()
    for sample in adapter.samples():
        if len(records) >= args.max_samples:
            break
        if sample.image_bytes:
            raw = np.frombuffer(sample.image_bytes, dtype=np.uint8)
            image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        elif sample.image_path and sample.image_path.is_file():
            image = cv2.imread(str(sample.image_path), cv2.IMREAD_COLOR)
        else:
            continue
        if image is None or image.size == 0:
            continue
        digest = hashlib.sha256(image.tobytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        sample_id = f"{sample.sample_id}_{digest[:8]}"
        image_name = f"{sample_id}.png"
        if not cv2.imwrite(str(out / image_name), image):
            continue
        html_name = None
        if sample.html:
            html_name = f"{sample_id}.html"
            (out / html_name).write_text(sample.html, encoding="utf-8")
        record = {
            "sample_id": sample_id,
            "source_dataset": sample.source_dataset,
            "source_license_spdx": source_record.get("license_spdx", "UNKNOWN"),
            "source_url": source_record.get("source_url"),
            "image": image_name,
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "html": html_name,
            "label": sample.label,
            "bboxes": sample.bboxes,
            "has_detection_labels": bool(sample.bboxes),
            "provenance": sample.provenance,
        }
        (out / f"{sample_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        records.append(record)
    manifest = {"schema_version": 1, "source_dataset": args.dataset,
                "source_license_spdx": source_record.get("license_spdx", "UNKNOWN"),
                "source_url": source_record.get("source_url"),
                "count": len(records), "has_detection_labels": any(r["has_detection_labels"]
                                                                     for r in records),
                "samples": records}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Processed {len(records)} image samples into {out}")
    print(f"Detection labels present: {manifest['has_detection_labels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
