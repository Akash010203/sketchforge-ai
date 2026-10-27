"""Pre-flight check before overnight training.

Verifies:
  - PyTorch + CUDA are working
  - Dataset is present and non-empty
  - GPU VRAM is sufficient for the configured batch size
  - Checkpoint directory is writable
  - config/overnight_train.yaml is valid YAML

Run: python scripts/preflight_check.py
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PASS = "[PASS]"
WARN = "[WARN]"
FAIL = "[FAIL]"

errors = 0
warnings = 0

def ok(msg): print(f"  {PASS} {msg}")
def warn(msg): global warnings; warnings += 1; print(f"  {WARN} {msg}")
def fail(msg): global errors; errors += 1; print(f"  {FAIL} {msg}")

print("=" * 60)
print("SketchForge Overnight Training — Pre-flight Check")
print("=" * 60)

# 1. PyTorch ----------------------------------------------------------------
print("\n[1] PyTorch & CUDA")
try:
    import torch
    ok(f"PyTorch {torch.__version__}")
    if torch.cuda.is_available():
        gpu = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        ok(f"CUDA available: {gpu} ({vram_gb:.1f} GB VRAM)")
        if vram_gb < 4.0:
            warn("Less than 4 GB VRAM — reduce batch_size to 8 in overnight_train.yaml")
        elif vram_gb < 6.0:
            warn("Less than 6 GB VRAM — batch_size 16 recommended")
        else:
            ok(f"VRAM sufficient for batch_size=24 at 416px")
    else:
        warn("CUDA not available — training will run on CPU (very slow)")
except ImportError:
    fail("PyTorch not installed. Run: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124")

# 2. Dataset ----------------------------------------------------------------
print("\n[2] Dataset")
processed = ROOT / "datasets" / "processed"
synthetic = ROOT / "datasets" / "synthetic"
raw       = ROOT / "datasets" / "raw"

if processed.exists():
    pngs = list(processed.rglob("*.png"))
    if len(pngs) >= 10:
        ok(f"datasets/processed: {len(pngs):,} PNG files")
    else:
        warn(f"datasets/processed exists but only {len(pngs)} PNG files — run scripts/process_datasets.py")
elif synthetic.exists():
    pngs = list(synthetic.glob("*.png"))
    if len(pngs) >= 10:
        warn(f"Using datasets/synthetic ({len(pngs)} PNGs). Real 40GB data not processed yet.")
        warn("Run: python scripts/process_datasets.py to use the full dataset")
    else:
        fail(f"datasets/synthetic has only {len(pngs)} PNGs. Run: python scripts/generate_synthetic_data.py --count 2000")
else:
    fail("No dataset found! Run: python scripts/generate_synthetic_data.py --count 2000")

if raw.exists():
    raw_datasets = [d.name for d in raw.iterdir() if d.is_dir() and d.name != "__pycache__"]
    if raw_datasets:
        ok(f"Raw datasets present: {raw_datasets}")
    else:
        warn("datasets/raw/ is empty — 40GB data not downloaded yet")

# 3. Config ----------------------------------------------------------------
print("\n[3] Config")
config_path = ROOT / "config" / "overnight_train.yaml"
if config_path.exists():
    try:
        import yaml
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        ok(f"overnight_train.yaml valid (epochs={cfg.get('epochs')}, batch={cfg.get('batch_size')}, device={cfg.get('device')})")
    except ImportError:
        warn("PyYAML not installed — config will not be validated (install: pip install pyyaml)")
    except Exception as e:
        fail(f"overnight_train.yaml parse error: {e}")
else:
    fail(f"Config not found: {config_path}")

# 4. Checkpoints dir -------------------------------------------------------
print("\n[4] Checkpoints")
ckpt_dir = ROOT / "checkpoints"
try:
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    test_file = ckpt_dir / ".write_test"
    test_file.write_text("ok")
    test_file.unlink()
    ok(f"checkpoints/ is writable")
    existing = list(ckpt_dir.glob("**/*.pt"))
    if existing:
        ok(f"Existing checkpoints found: {len(existing)} .pt files")
    else:
        ok("No existing checkpoints — fresh run")
except Exception as e:
    fail(f"Cannot write to checkpoints/: {e}")

# 5. Architecture import ---------------------------------------------------
print("\n[5] Model Architecture")
try:
    from sketchforge.models.component_detector.architecture import build_model
    model = build_model(num_classes=15)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    ok(f"Model builds OK — {n_params:,} trainable parameters")
except Exception as e:
    fail(f"Cannot import model: {e}")

# 6. Summary ---------------------------------------------------------------
print()
print("=" * 60)
if errors == 0 and warnings == 0:
    print(f"ALL CHECKS PASSED. Ready for overnight training!")
elif errors == 0:
    print(f"READY with {warnings} warning(s). Review above before starting.")
else:
    print(f"NOT READY: {errors} error(s), {warnings} warning(s). Fix errors before training.")
print()
print("To launch overnight training:")
print("  powershell -ExecutionPolicy Bypass -File scripts\\overnight_train.ps1")
print("=" * 60)

sys.exit(0 if errors == 0 else 1)
