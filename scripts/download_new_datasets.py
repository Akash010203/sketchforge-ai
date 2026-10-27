"""Download free, open-access UI datasets with bounding box annotations.

Datasets:
  mrtoy-mobile-ui  -- mrtoy/mobile-ui-design on HuggingFace (mobile UI bboxes)
  rico             -- RICO Android UI 66k screenshots (HuggingFace mirror)
  roboflow-guide   -- Print instructions for downloading from Roboflow Universe

Usage:
  python scripts/download_new_datasets.py --dataset mrtoy-mobile-ui
  python scripts/download_new_datasets.py --dataset rico
  python scripts/download_new_datasets.py --dataset all
  python scripts/download_new_datasets.py --dataset roboflow-guide
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------

def download_mrtoy(dest: Path) -> None:
    """Download mrtoy/mobile-ui-design from HuggingFace and save to disk."""
    print("=" * 60)
    print("Downloading: mrtoy/mobile-ui-design")
    print("Source: https://huggingface.co/datasets/mrtoy/mobile-ui-design")
    print(f"Destination: {dest}")
    print("=" * 60)

    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        print("ERROR: huggingface datasets not installed.")
        print("Run: pip install datasets pillow")
        return

    print("Fetching dataset metadata from HuggingFace...")
    try:
        ds = load_dataset("mrtoy/mobile-ui-design", split="train",
                          cache_dir=str(dest / ".cache"))
    except Exception as exc:
        print(f"ERROR: Could not load dataset: {exc}")
        print("Check your internet connection and try again.")
        return

    print(f"Downloaded {len(ds)} samples.")
    save_path = dest / "dataset"
    print(f"Saving to disk at {save_path} ...")
    ds.save_to_disk(str(save_path))
    print(f"Done. {len(ds)} samples saved.")
    print()
    print("To use in training:")
    print(f'  python scripts/process_datasets.py --dataset mrtoy-mobile-ui')


def download_rico(dest: Path) -> None:
    """Download RICO from HuggingFace (creative-graphic-design/Rico)."""
    print("=" * 60)
    print("Downloading: RICO Android UI Dataset")
    print("Source: https://huggingface.co/datasets/Voxel51/rico")
    print(f"Destination: {dest}")
    print("=" * 60)
    print()
    print("The official Voxel51 mirror is approximately 8.3 GB and uses CC-BY-4.0.")
    print("It includes semantic UI detections and is saved in the format read by RICOAdapter.")
    print()

    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        print("ERROR: huggingface datasets not installed.")
        print("Run: pip install -e '.[data]'")
        return

    print("Fetching RICO from HuggingFace (this may take a while)...")
    try:
        ds = load_dataset(
            "Voxel51/rico",
            split="train",
            cache_dir=str(dest / ".cache"),
        )
    except Exception as exc:
        print(f"ERROR: Could not load the licensed Voxel51 mirror: {exc}")
        print("No fallback dataset was substituted, to avoid misattributing source and license.")
        return

    print(f"Downloaded {len(ds)} samples.")
    save_path = dest / "dataset"
    print(f"Saving to disk at {save_path} ...")
    ds.save_to_disk(str(save_path))
    print(f"Done. {len(ds)} RICO samples saved.")
    print()
    print("To use in training:")
    print("  python scripts/process_datasets.py --dataset rico")


def roboflow_guide() -> None:
    """Print step-by-step guide for downloading a Roboflow wireframe dataset."""
    print("=" * 60)
    print("How to Download a Wireframe Dataset from Roboflow Universe")
    print("=" * 60)
    print()
    print("Roboflow Universe hosts free, pre-annotated wireframe/UI datasets")
    print("in COCO format. Follow these steps:")
    print()
    print("STEP 1 — Go to Roboflow Universe:")
    print("  https://universe.roboflow.com")
    print()
    print("STEP 2 — Search for a wireframe dataset. Good searches:")
    print("  - 'UI wireframe'")
    print("  - 'wireframe sketch'")
    print("  - 'UI components sketch'")
    print()
    print("STEP 3 — Recommended datasets (copy-paste into search):")
    print("  - 'Wireframes Object Detection' by codefree")
    print("  - 'UI Det'")
    print("  - 'sketch-it'")
    print()
    print("STEP 4 — Click 'Download Dataset' on any dataset.")
    print("  - Choose format: COCO (NOT YOLOv5)")
    print("  - Click Download ZIP")
    print()
    print("STEP 5 — Extract the ZIP into:")
    print(f"  {ROOT / 'datasets' / 'raw' / 'roboflow-wireframe' / ''}")
    print()
    print("  The folder should contain:")
    print("    datasets/raw/roboflow-wireframe/")
    print("      train/")
    print("        _annotations.coco.json")
    print("        image1.jpg  image2.jpg  ...")
    print("      valid/")
    print("        _annotations.coco.json")
    print()
    print("STEP 6 — Process and use in training:")
    print("  python scripts/process_datasets.py --dataset roboflow-wireframe")
    print()
    print("That's it! The RoboflowCOCOAdapter handles everything automatically.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--dataset",
        required=True,
        choices=["mrtoy-mobile-ui", "rico", "roboflow-guide", "all"],
        help="Which dataset to download",
    )
    args = ap.parse_args()

    if args.dataset in ("mrtoy-mobile-ui", "all"):
        dest = ROOT / "datasets" / "raw" / "mrtoy-mobile-ui"
        dest.mkdir(parents=True, exist_ok=True)
        download_mrtoy(dest)
        print()

    if args.dataset in ("rico", "all"):
        dest = ROOT / "datasets" / "raw" / "rico"
        dest.mkdir(parents=True, exist_ok=True)
        download_rico(dest)
        print()

    if args.dataset in ("roboflow-guide", "all"):
        roboflow_guide()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
