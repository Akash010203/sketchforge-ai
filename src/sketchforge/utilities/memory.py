"""In-process memory inspection and budget helpers.

All public functions are read-only: they query, they never allocate or free.

RAM queries
-----------
* :func:`ram_total_gb` / :func:`ram_available_gb` — system RAM via ``psutil``
  (preferred), the Windows API (fallback), or ``/proc/meminfo`` (Linux).

VRAM queries
------------
* :func:`vram_total_gb` / :func:`vram_available_gb` — GPU memory via
  ``torch.cuda`` (always present given the project's PyTorch dependency).
  If ``pynvml`` is installed, :func:`vram_process_gb` also reports how much
  VRAM *this* process currently holds.

Budget helpers
--------------
* :func:`check_ram_budget` / :func:`check_vram_budget` raise
  :class:`~sketchforge.exceptions.BudgetExceededError` when the available
  memory falls below a caller-supplied threshold.
* :func:`memory_snapshot` returns a flat ``dict`` suitable for logging or
  JSON serialisation.

The module never imports anything that is not part of the project's declared
dependencies (torch, psutil is optional but usually present; pynvml is purely
optional).
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass, field
from typing import Any

from sketchforge.exceptions import BudgetExceededError

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gib(n: float) -> float:
    """Round a byte count to GiB with 3 decimal places."""
    return round(n / 1024 ** 3, 3)


# ── RAM ────────────────────────────────────────────────────────────────────

def _ram_via_psutil() -> tuple[float, float] | None:
    """Return (total_bytes, available_bytes) using psutil, or None if absent."""
    try:
        import psutil  # type: ignore[import]
        vm = psutil.virtual_memory()
        return float(vm.total), float(vm.available)
    except Exception:  # noqa: BLE001
        return None


def _ram_via_winapi() -> tuple[float, float] | None:
    """Return (total_bytes, available_bytes) using the Windows GlobalMemoryStatusEx API."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        import ctypes.wintypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.wintypes.DWORD),
                ("dwMemoryLoad", ctypes.wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return float(stat.ullTotalPhys), float(stat.ullAvailPhys)
    except Exception:  # noqa: BLE001
        return None


def _ram_via_procmeminfo() -> tuple[float, float] | None:
    """Return (total_bytes, available_bytes) from /proc/meminfo (Linux)."""
    try:
        info: dict[str, float] = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    info[key.strip()] = float(parts[0]) * 1024  # kB → bytes
        return info["MemTotal"], info.get("MemAvailable", 0.0)
    except (OSError, KeyError, ValueError):
        return None


def _ram_bytes() -> tuple[float, float]:
    """Return (total_bytes, available_bytes); (0, 0) if every backend fails."""
    for backend in (_ram_via_psutil, _ram_via_winapi, _ram_via_procmeminfo):
        result = backend()
        if result is not None:
            return result
    _log.warning("memory.py: all RAM backends failed; returning zeros")
    return 0.0, 0.0


# ── VRAM ───────────────────────────────────────────────────────────────────

def _vram_bytes_torch(device: int = 0) -> tuple[float, float]:
    """Return (total_bytes, free_bytes) for *device* via torch.cuda.

    Falls back to (0, 0) when CUDA is unavailable or *device* is out of range.
    """
    try:
        import torch  # type: ignore[import]
        if not torch.cuda.is_available():
            return 0.0, 0.0
        if device >= torch.cuda.device_count():
            return 0.0, 0.0
        free, total = torch.cuda.mem_get_info(device)
        return float(total), float(free)
    except Exception:  # noqa: BLE001
        return 0.0, 0.0


def _vram_process_bytes_nvml(device: int = 0) -> float | None:
    """Return bytes used by *this process* on *device* via pynvml, or None."""
    try:
        import pynvml  # type: ignore[import]
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device)
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        pid = os.getpid()
        for p in procs:
            if p.pid == pid:
                return float(p.usedGpuMemory)
        return 0.0
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Public API — individual queries
# ---------------------------------------------------------------------------

def ram_total_gb() -> float:
    """Total system RAM in GiB (gibibytes, 3 decimal places)."""
    total, _ = _ram_bytes()
    return _gib(total)


def ram_available_gb() -> float:
    """Available (free + reclaimable) system RAM in GiB."""
    _, avail = _ram_bytes()
    return _gib(avail)


def vram_total_gb(device: int = 0) -> float:
    """Total VRAM on *device* in GiB.  Returns 0 if CUDA is unavailable."""
    total, _ = _vram_bytes_torch(device)
    return _gib(total)


def vram_available_gb(device: int = 0) -> float:
    """Free (currently unallocated) VRAM on *device* in GiB."""
    _, free = _vram_bytes_torch(device)
    return _gib(free)


def vram_process_gb(device: int = 0) -> float | None:
    """VRAM held by *this process* on *device* in GiB, or ``None`` if pynvml is absent."""
    result = _vram_process_bytes_nvml(device)
    return _gib(result) if result is not None else None


def gpu_device_count() -> int:
    """Number of CUDA devices visible to PyTorch (0 if CUDA unavailable)."""
    try:
        import torch  # type: ignore[import]
        return torch.cuda.device_count() if torch.cuda.is_available() else 0
    except Exception:  # noqa: BLE001
        return 0


def gpu_device_name(device: int = 0) -> str | None:
    """Human-readable name of *device* from PyTorch, or ``None``."""
    try:
        import torch  # type: ignore[import]
        if not torch.cuda.is_available() or device >= torch.cuda.device_count():
            return None
        return torch.cuda.get_device_name(device)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Public API — structured snapshot
# ---------------------------------------------------------------------------

@dataclass
class MemorySnapshot:
    """Point-in-time view of system RAM and VRAM for all visible GPU devices.

    Sizes are in GiB (gibibytes).  Construct with :func:`memory_snapshot`.
    """

    ram_total_gb: float
    ram_available_gb: float
    devices: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ram_total_gb": self.ram_total_gb,
            "ram_available_gb": self.ram_available_gb,
            "devices": self.devices,
        }

    def __str__(self) -> str:
        lines = [
            f"RAM  total={self.ram_total_gb:.2f} GiB  available={self.ram_available_gb:.2f} GiB",
        ]
        for dev in self.devices:
            proc = f"  process={dev['vram_process_gb']:.3f} GiB" if dev.get("vram_process_gb") is not None else ""
            lines.append(
                f"GPU{dev['index']} {dev.get('name', 'unknown')}  "
                f"total={dev['vram_total_gb']:.2f} GiB  "
                f"free={dev['vram_available_gb']:.2f} GiB{proc}"
            )
        return "\n".join(lines)


def memory_snapshot() -> MemorySnapshot:
    """Capture a complete RAM + VRAM snapshot for all visible CUDA devices.

    Safe to call from any thread; read-only.
    """
    total, avail = _ram_bytes()
    devices: list[dict[str, Any]] = []
    for idx in range(gpu_device_count()):
        vram_total, vram_free = _vram_bytes_torch(idx)
        proc_bytes = _vram_process_bytes_nvml(idx)
        devices.append(
            {
                "index": idx,
                "name": gpu_device_name(idx),
                "vram_total_gb": _gib(vram_total),
                "vram_available_gb": _gib(vram_free),
                "vram_process_gb": _gib(proc_bytes) if proc_bytes is not None else None,
            }
        )
    return MemorySnapshot(
        ram_total_gb=_gib(total),
        ram_available_gb=_gib(avail),
        devices=devices,
    )


# ---------------------------------------------------------------------------
# Public API — budget checks (raise on failure)
# ---------------------------------------------------------------------------

def check_ram_budget(required_gb: float, *, label: str = "") -> None:
    """Raise :class:`~sketchforge.exceptions.BudgetExceededError` if fewer than
    *required_gb* GiB of RAM are currently available.

    Parameters
    ----------
    required_gb:
        Minimum free RAM in GiB that the caller needs.
    label:
        Optional context string included in the error message (e.g. the name
        of the operation about to run).
    """
    if required_gb <= 0:
        return
    available = ram_available_gb()
    if available < required_gb:
        ctx = f" for {label!r}" if label else ""
        raise BudgetExceededError(
            f"Insufficient RAM{ctx}: need {required_gb:.2f} GiB, "
            f"only {available:.2f} GiB available"
        )


def check_vram_budget(required_gb: float, device: int = 0, *, label: str = "") -> None:
    """Raise :class:`~sketchforge.exceptions.BudgetExceededError` if fewer than
    *required_gb* GiB of VRAM are free on *device*.

    Parameters
    ----------
    required_gb:
        Minimum free VRAM in GiB.
    device:
        CUDA device index (default: 0).
    label:
        Optional context string for the error message.
    """
    if required_gb <= 0:
        return
    if gpu_device_count() == 0:
        _log.warning(
            "check_vram_budget: CUDA not available — skipping VRAM budget check"
            + (f" for {label!r}" if label else "")
        )
        return
    available = vram_available_gb(device)
    if available < required_gb:
        ctx = f" for {label!r}" if label else ""
        name = gpu_device_name(device) or f"device {device}"
        raise BudgetExceededError(
            f"Insufficient VRAM{ctx} on {name}: need {required_gb:.2f} GiB, "
            f"only {available:.2f} GiB free"
        )


__all__ = [
    # single-value queries
    "ram_total_gb",
    "ram_available_gb",
    "vram_total_gb",
    "vram_available_gb",
    "vram_process_gb",
    "gpu_device_count",
    "gpu_device_name",
    # structured snapshot
    "MemorySnapshot",
    "memory_snapshot",
    # budget guards
    "check_ram_budget",
    "check_vram_budget",
]
