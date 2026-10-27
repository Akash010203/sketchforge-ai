"""Train the compact component detector from random initialization.

Runs the full training pipeline on the synthetic dataset (or a real one if
the manifest is configured).  Before starting a full training run, a smoke
test verifies the entire pipeline works end-to-end (1 epoch, 2 batches).

Usage
-----
    # Quick smoke test only (no checkpoint saved):
    python -I scripts/train_component_detector.py --smoke-test

    # Full training run with default config:
    python -I scripts/train_component_detector.py

    # Custom config:
    python -I scripts/train_component_detector.py \\
        --data datasets/synthetic \\
        --epochs 50 --batch-size 16 --lr 1e-3 --device cuda

Requirements
------------
* PyTorch must be installed.
* Run ``scripts/generate_synthetic_data.py`` first to populate datasets/synthetic.
* The checkpoint will be written to ``checkpoints/component_detector_v1/``.
* Training progress is printed to stdout and saved as a JSON report.

Important limitations (see docs/KNOWN_LIMITATIONS.md)
------------------------------------------------------
* The model is trained on synthetic sketches only.
* Claimed metrics are held-out (not training) numbers.
* Do not compare against a baseline before the model actually outperforms it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sketchforge.training.config import TrainingConfig  # noqa: E402
from sketchforge.training.trainer import train  # noqa: E402


def _data_ready(data_dir: Path) -> bool:
    """Return True if the synthetic dataset directory has at least 10 images."""
    if not data_dir.is_dir():
        return False
    return len(list(data_dir.glob("*.png"))) >= 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default="datasets/synthetic",
                    help="Path to training data directory (default: datasets/synthetic)")
    ap.add_argument("--epochs", type=int, default=None,
                    help="Number of epochs (overrides config default)")
    ap.add_argument("--batch-size", type=int, default=None,
                    help="Batch size (overrides config default)")
    ap.add_argument("--lr", type=float, default=None,
                    help="Learning rate (overrides config default)")
    ap.add_argument("--device", default=None,
                    help='Device override: "auto" | "cuda" | "cpu" (default: auto)')
    ap.add_argument("--seed", type=int, default=None,
                    help="Random seed (default: 42)")
    ap.add_argument("--checkpoint-dir", default="checkpoints",
                    help="Directory to save checkpoints (default: checkpoints)")
    ap.add_argument("--smoke-test", action="store_true",
                    help="Run one epoch / two batches only to verify the pipeline")
    ap.add_argument("--config", default=None,
                    help="Path to a YAML training config (overrides CLI flags)")
    args = ap.parse_args()

    # ------------------------------------------------------------------ config
    if args.config:
        cfg = TrainingConfig.from_yaml(args.config)
        print(f"Loaded config from {args.config}")
    else:
        cfg = TrainingConfig()

    # Apply CLI overrides
    if args.data:
        cfg.data_dir = str((ROOT / args.data).resolve())
    if args.epochs is not None:
        cfg.epochs = args.epochs
    if args.batch_size is not None:
        cfg.batch_size = args.batch_size
    if args.lr is not None:
        cfg.learning_rate = args.lr
    if args.device is not None:
        cfg.device = args.device
    if args.seed is not None:
        cfg.seed = args.seed
    cfg.checkpoint_dir = str((ROOT / args.checkpoint_dir).resolve())

    # ------------------------------------------------------------------ pre-checks
    data_path = Path(cfg.data_dir)
    if not _data_ready(data_path):
        print(
            f"ERROR: training data not ready at {data_path}\n"
            "  Run: python -I scripts/generate_synthetic_data.py --count 500\n"
            "  to generate the synthetic dataset first."
        )
        return 1

    n_images = len(list(data_path.glob("*.png")))
    device_str = cfg.resolve_device()
    print("=" * 60)
    print("SketchForge Component Detector Training")
    print("=" * 60)
    print(f"  Data:       {data_path} ({n_images} images)")
    print(f"  Device:     {device_str}")
    if device_str == "cuda":
        import torch
        print(f"  GPU:        {torch.cuda.get_device_name(0)}")
        print(f"  CUDA AMP:   {'on' if cfg.mixed_precision else 'off'}")
        print(f"  Layout:     {'channels_last' if cfg.channels_last else 'contiguous'}")
    print(f"  Epochs:     {cfg.epochs if not args.smoke_test else '1 (smoke test)'}")
    print(f"  Batch size: {cfg.batch_size}")
    print(f"  Lr:         {cfg.learning_rate}")
    print(f"  Checkpoint: {cfg.checkpoint_dir}")
    print(f"  Seed:       {cfg.seed}")
    print()

    if args.smoke_test:
        print("SMOKE TEST MODE — verifying data loading, forward pass, loss, backprop, checkpoint …")
    else:
        print("Starting full training run. Press Ctrl+C to stop early (checkpoint is kept).")
    print()

    # ------------------------------------------------------------------ train
    t0 = time.perf_counter()
    try:
        report = train(cfg, smoke_test=args.smoke_test)
    except KeyboardInterrupt:
        print("\nInterrupted by user — checkpoint should have been saved.")
        return 0
    except ImportError as exc:
        print(f"ERROR: {exc}")
        print("  Install PyTorch: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124")
        return 1

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 60)
    print(f"Training {'smoke test' if args.smoke_test else 'run'} completed in {elapsed:.1f}s")

    if report.final_test_metrics:
        tr = report.final_test_metrics.to_dict()
        print(f"  Test anchor acc: {tr.get('accuracy', 0):.4f}")
        print(f"  Test loss:     {tr.get('loss', 0):.4f}")
        print(f"  Test IoU:      {tr.get('mean_iou', 0):.4f}")
        print(f"  Test mAP (avg @0.25/0.35/0.50): {tr.get('mAP', 0):.4f}")
        print(f"  Test mAP@0.50: {tr.get('mAP@0.50', 0):.4f}")

    print(f"  Best checkpoint epoch: {report.best_epoch}")
    print(f"  Best val mAP@0.25:     {report.best_val_map:.4f}")
    print()

    # Save report
    report_path = ROOT / "experiments" / "results" / "training_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_dict = {
        "model_name": cfg.model_name,
        "smoke_test": args.smoke_test,
        "epochs_run": sum(metric.phase == "train" for metric in report.epochs),
        "best_epoch": report.best_epoch,
        "best_val_metric": report.best_val_map,
        "best_val_loss": report.best_val_loss,
        "test_results": report.final_test_metrics.to_dict() if report.final_test_metrics else None,
        "elapsed_seconds": round(elapsed, 1),
        "config": {
            "data_dir": cfg.data_dir,
            "epochs": cfg.epochs,
            "batch_size": cfg.batch_size,
            "learning_rate": cfg.learning_rate,
            "device": device_str,
            "seed": cfg.seed,
            "mixed_precision": cfg.mixed_precision,
            "channels_last": cfg.channels_last,
        },
    }
    report_path.write_text(json.dumps(report_dict, indent=2) + "\n", encoding="utf-8")
    print(f"Report saved to {report_path.relative_to(ROOT)}")

    if args.smoke_test and not report.epochs:
        print("SMOKE TEST FAILED — no epoch metrics recorded.")
        return 1

    print("OK" if args.smoke_test else "Training complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
