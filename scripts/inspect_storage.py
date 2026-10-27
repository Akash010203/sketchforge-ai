"""Report free disk space and what this repository already occupies, with a download budget.

    .venv/bin/python -I scripts/inspect_storage.py [--path DIR] [--need-gb N]

Dataset downloads must fit in the budget this prints: compressed archive + expanded files + caches
+ processed output + checkpoints. A dataset that does not fit is not downloaded (see
docs/DATASET_AUDIT.md). Read-only.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Directories that grow: (relative path, what it holds)
TRACKED = [
    ("datasets/raw", "downloaded source data"), ("datasets/processed", "prepared training data"),
    ("datasets/synthetic", "generated sketch/design pairs"), ("checkpoints", "model checkpoints"),
    ("experiments/results", "benchmark and training results"), ("output", "demo and project outputs"),
    (".venv", "Python environment"),
]
SAFETY_FRACTION = 0.5  # never plan to use more than half of what is free


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def gb(n: float) -> float:
    return round(n / 1024**3, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--path", default=str(ROOT), help="filesystem to inspect (default: the repository)")
    ap.add_argument("--need-gb", type=float, help="exit 1 if this much does not fit in the budget")
    args = ap.parse_args()
    usage = shutil.disk_usage(args.path)
    budget = usage.free * SAFETY_FRACTION
    print(f"filesystem of {args.path}")
    print(f"  total {gb(usage.total):>9.2f} GB   used {gb(usage.used):>9.2f} GB   free {gb(usage.free):>9.2f} GB")
    print(f"  planning budget (free x {SAFETY_FRACTION}): {gb(budget):.2f} GB")
    print("this repository:")
    for rel, what in TRACKED:
        print(f"  {rel:22s} {gb(dir_size(ROOT / rel)):>8.3f} GB  {what}")
    if args.need_gb is not None:
        fits = args.need_gb * 1024**3 <= budget
        print(f"need {args.need_gb:.2f} GB -> {'fits' if fits else 'DOES NOT FIT'} within the budget")
        return 0 if fits else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
