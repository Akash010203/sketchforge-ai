#!/usr/bin/env python
"""Audit candidate dataset licenses and storage cost without downloading data."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sketchforge.datasets.license_audit import license_audit, load_manifest  # noqa: E402
from sketchforge.datasets.manifest_schema import TRAINING_LICENSES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAFETY_FRACTION = 0.5


def make_report(manifest_path: Path) -> tuple[dict, str]:
    manifest = load_manifest(manifest_path)
    usage = shutil.disk_usage(ROOT)
    budget = int(usage.free * SAFETY_FRACTION)
    license_rows = {row["id"]: row for row in license_audit(manifest)}
    candidates = []
    for record in manifest.datasets:
        row = license_rows[record.id]
        estimate = record.expected_download_bytes
        candidates.append({
            "id": record.id, "name": record.name, "source_url": record.source_url,
            "license_spdx": record.license_spdx, "access": record.access,
            "training_eligible": row["training_eligible"],
            "expected_download_bytes": estimate,
            "fits_half_free_space": estimate is not None and estimate <= budget,
            "decision": "eligible_for_pilot_review" if row["training_eligible"] and record.access == "public"
                       else "blocked_pending_rights_or_license_review",
            "notes": record.notes,
        })
    report = {
        "reviewed_on": date.today().isoformat(),
        "manifest": str(manifest_path.relative_to(ROOT)) if manifest_path.is_relative_to(ROOT) else str(manifest_path),
        "disk": {"free_bytes": usage.free, "planning_budget_bytes": budget,
                 "safety_fraction": SAFETY_FRACTION},
        "approved_training_licenses": sorted(TRAINING_LICENSES),
        "datasets": candidates,
        "pilot_downloaded": False,
        "reason_no_download": "No reviewed candidate is both clearly licensed for the requested use and within the pilot policy.",
    }
    lines = [
        "# Dataset Audit",
        "",
        f"Reviewed: {report['reviewed_on']}",
        "",
        "This is a provenance and policy screen, not legal advice. The training allowlist is Apache-2.0, MIT, and MPL-2.0.",
        "A code repository license does not establish the license for its dataset. Unknown or inherited data terms stay blocked.",
        "",
        f"Current filesystem free space: {usage.free / 1024**3:.2f} GiB; conservative planning budget (50%): {budget / 1024**3:.2f} GiB.",
        "",
        "| Candidate | Dataset license | Access | Size estimate | Training | Decision |",
        "|---|---|---|---:|---|---|",
    ]
    for item in candidates:
        size = (f"{item['expected_download_bytes'] / 1024**3:.2f} GiB"
                if item["expected_download_bytes"] is not None else "unknown")
        lines.append(f"| [{item['name']}]({item['source_url']}) | `{item['license_spdx']}` | {item['access']} | {size} | "
                     f"{'eligible' if item['training_eligible'] else 'blocked'} | {item['decision']} |")
    lines += [
        "",
        "## Findings",
        "",
        "- **SALT-NLP Sketch2Code:** its [repository](https://github.com/SALT-NLP/Sketch2Code) says the dataset follows Design2Code's data terms. The [Design2Code dataset card](https://huggingface.co/datasets/SALT-NLP/Design2Code-hf) identifies ODC-By; the [official project README](https://github.com/NoviScl/Design2Code) limits use to research. The dataset is not approved for training under this project's allowlist.",
        "- **WebSight:** its [dataset card](https://huggingface.co/datasets/HuggingFaceM4/WebSight/blob/10d8285c49c88608dcf82f3f76ee58377a3a1216/README.md) states CC-BY-4.0, requires compliance with original source-content licenses, and requires disclosure when releasing a trained model/application. Its listed compressed size is about 29.24 GiB, so it is not a sub-1-GiB pilot candidate as a full download.",
        "- **ImageCLEFdrawnUI 2021:** the [official task page](https://www.imageclef.org/2021/drawnui) describes the hand-drawn wireframe dataset but does not state a reusable dataset license or provide an unconditional download. Access and rights require confirmation.",
        "",
        "## Pilot decision",
        "",
        "No external pilot files were downloaded. Current candidates lack clear approval under the project's Apache-2.0/MIT/MPL-2.0 training policy, or have source-rights/access conditions that need review. Continue with the repository's synthetic generator until an eligible source and explicit subset are identified.",
        "",
        "Source records and pinned metadata are in [`datasets/manifests/manifest.json`](../datasets/manifests/manifest.json). Re-run `python scripts/audit_datasets.py` after updating it.",
        "",
    ]
    return report, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="datasets/manifests/manifest.json")
    parser.add_argument("--out", default="docs/DATASET_AUDIT.md")
    parser.add_argument("--json-out", help="optional machine-readable audit report")
    args = parser.parse_args()
    report, markdown = make_report(Path(args.manifest).resolve())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"candidates": len(report["datasets"]), "pilot_downloaded": False,
                      "report": str(out), "free_gib": round(report["disk"]["free_bytes"] / 1024**3, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
