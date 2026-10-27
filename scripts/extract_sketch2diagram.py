"""Safely extract the Sketch2Diagram benchmark archive into its raw-data folder."""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path,
                        default=ROOT / "datasets/raw/sketch2diagram/Sketch2Diagram Benchmark.zip")
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "datasets/raw/sketch2diagram")
    args = parser.parse_args()
    archive = args.archive.resolve()
    destination = args.destination.resolve()
    if not archive.is_file():
        parser.error(f"archive not found: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"archive path escapes destination: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            written += 1
    print(f"Extracted {written} files under {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
