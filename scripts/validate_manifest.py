#!/usr/bin/env python
"""Validate dataset-manifest schema, hashes and approved training-license status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sketchforge.datasets.license_audit import license_audit, load_manifest  # noqa: E402
from sketchforge.datasets.manifest_schema import validate_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", default="datasets/manifests/manifest.json")
    parser.add_argument("--artifact-root", help="root directory for validating artifact paths")
    parser.add_argument("--require-training-eligible", action="store_true",
                        help="fail when any listed dataset is not on the Apache-2.0/MIT/MPL-2.0 allowlist")
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
    except ValueError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    license_rows = license_audit(manifest)
    errors = validate_artifacts(manifest, args.artifact_root) if args.artifact_root else []
    for row in license_rows:
        print(f"{row['id']}: {row['license_spdx']} -> {row['status']}")
    if args.require_training_eligible:
        errors.extend(f"{row['id']}: not approved for training ({row['license_spdx']})"
                      for row in license_rows if not row["training_eligible"])
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if not errors:
        print(f"VALID: {len(manifest.datasets)} dataset record(s), schema v{manifest.schema_version}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
