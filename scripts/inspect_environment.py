"""Report the machine, toolchain and optional accelerators this project would run on.

    .venv/bin/python -I scripts/inspect_environment.py [--json]

Read-only: it inspects, it does not install anything or touch the network.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or out.stderr).strip() or None


def _version(module: str) -> str | None:
    try:
        mod = importlib.import_module(module)
    except Exception:  # noqa: BLE001 - absence or a broken install both mean "unavailable"
        return None
    return str(getattr(mod, "__version__", "installed"))


def _mem_gb() -> tuple[float | None, float | None]:
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key] = float(rest.split()[0]) / 1024 / 1024  # kB -> GB
        return round(info["MemTotal"], 2), round(info.get("MemAvailable", 0.0), 2)
    except (OSError, KeyError, ValueError):
        return None, None


def gather() -> dict:
    total, avail = _mem_gb()
    nvidia = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    torch_info: dict | None = None
    if _version("torch"):
        import torch  # type: ignore

        torch_info = {"version": torch.__version__, "cuda_available": bool(torch.cuda.is_available()),
                      "cuda_version": torch.version.cuda}
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_gb_total": total,
        "ram_gb_available": avail,
        "gpu": nvidia or "none detected (nvidia-smi unavailable or reports no device)",
        "python": sys.version.split()[0],
        "node": _run(["node", "--version"]),
        "npm": _run(["npm", "--version"]),
        "git": _run(["git", "--version"]),
        "uv": _run(["uv", "--version"]),
        "libraries": {m: _version(m) for m in ("numpy", "cv2", "PIL", "pydantic", "yaml", "PySide6", "torch", "pytest", "ruff")},
        "torch": torch_info,
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", "(default)"),
        "display": bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    info = gather()
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    for key, value in info.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for k, v in value.items():
                print(f"  {k:10s} {v if v is not None else '-'}")
        else:
            print(f"{key:16s} {value if value is not None else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
