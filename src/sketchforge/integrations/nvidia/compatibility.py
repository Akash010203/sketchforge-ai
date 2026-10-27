"""NVIDIA hardware and software compatibility checks.

This module inspects the local machine for CUDA availability, driver version,
device capabilities, and PyTorch build compatibility.  It is **read-only** —
it never modifies settings, installs packages, or changes environment state.

All results are recorded in a :class:`CompatibilityReport` that the rest of
the integration layer (and the UI's settings dialog) can query.  If torch is
not installed the report still returns a safe, fully-populated object with all
GPU fields set to ``None``.

Usage::

    from sketchforge.integrations.nvidia.compatibility import check_compatibility
    report = check_compatibility()
    if not report.cuda_available:
        print("No CUDA GPU detected; running on CPU.")
"""
from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Minimum requirements (informational — not enforced as hard errors)
MIN_CUDA_VERSION = (11, 8)   # (major, minor)
MIN_DRIVER_VERSION = 520     # NVIDIA display driver build number
MIN_VRAM_MiB = 2048          # 2 GiB — below this training is impractical
RECOMMENDED_VRAM_MiB = 6144  # 6 GiB — RTX 4050 laptop territory


@dataclass
class DeviceInfo:
    """Information about one CUDA-capable GPU device."""
    index: int
    name: str
    vram_mib: int
    compute_capability: tuple[int, int]
    is_primary: bool = False

    @property
    def vram_gib(self) -> float:
        return round(self.vram_mib / 1024, 2)

    @property
    def compute_str(self) -> str:
        return f"{self.compute_capability[0]}.{self.compute_capability[1]}"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "vram_mib": self.vram_mib,
            "vram_gib": self.vram_gib,
            "compute_capability": self.compute_str,
            "is_primary": self.is_primary,
        }


@dataclass
class CompatibilityReport:
    """Full compatibility snapshot for the local machine.

    All fields are populated on construction; call :func:`check_compatibility`
    instead of instantiating this directly.
    """
    # Python / platform
    python_version: str = ""
    platform_str: str = ""

    # PyTorch
    torch_available: bool = False
    torch_version: str | None = None
    torch_cuda_version: str | None = None   # the CUDA toolkit torch was built against

    # CUDA runtime
    cuda_available: bool = False
    cuda_runtime_version: str | None = None  # e.g. "12.4"
    driver_version: str | None = None        # NVIDIA display driver, e.g. "591.74"

    # Devices
    device_count: int = 0
    devices: list[DeviceInfo] = field(default_factory=list)
    primary_device: DeviceInfo | None = None

    # Derived verdicts
    meets_min_vram: bool = False
    meets_recommended_vram: bool = False
    meets_cuda_version: bool = False
    trt_available: bool = False   # TensorRT Python bindings installed

    # Human-readable summary
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when CUDA is available and minimum requirements are met."""
        return self.cuda_available and self.meets_min_vram and self.meets_cuda_version

    def to_dict(self) -> dict:
        return {
            "python_version": self.python_version,
            "platform": self.platform_str,
            "torch_available": self.torch_available,
            "torch_version": self.torch_version,
            "torch_cuda_version": self.torch_cuda_version,
            "cuda_available": self.cuda_available,
            "cuda_runtime_version": self.cuda_runtime_version,
            "driver_version": self.driver_version,
            "device_count": self.device_count,
            "devices": [d.to_dict() for d in self.devices],
            "primary_device": self.primary_device.to_dict() if self.primary_device else None,
            "meets_min_vram": self.meets_min_vram,
            "meets_recommended_vram": self.meets_recommended_vram,
            "meets_cuda_version": self.meets_cuda_version,
            "trt_available": self.trt_available,
            "ok": self.ok,
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def summary(self) -> str:
        """One-line human-readable status."""
        if not self.torch_available:
            return "PyTorch not installed — GPU acceleration unavailable"
        if not self.cuda_available:
            return "CUDA not available — running on CPU"
        name = self.primary_device.name if self.primary_device else "unknown GPU"
        vram = self.primary_device.vram_gib if self.primary_device else 0
        cuda = self.cuda_runtime_version or "?"
        return f"CUDA {cuda} · {name} ({vram:.1f} GiB VRAM)"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_compatibility() -> CompatibilityReport:
    """Inspect the local environment and return a :class:`CompatibilityReport`.

    Never raises — all failures are captured inside the report's ``errors``
    list so callers always get a usable object.
    """
    report = CompatibilityReport(
        python_version=sys.version.split()[0],
        platform_str=platform.platform(),
    )

    try:
        import torch  # type: ignore[import]
    except ImportError:
        report.errors.append("PyTorch is not installed.  Run: pip install torch torchvision")
        return report

    report.torch_available = True
    report.torch_version = torch.__version__

    # CUDA toolkit version torch was built with
    try:
        report.torch_cuda_version = torch.version.cuda or None
    except Exception:  # noqa: BLE001
        pass

    if not torch.cuda.is_available():
        report.warnings.append("torch.cuda.is_available() returned False — no CUDA GPU detected.")
        return report

    report.cuda_available = True

    # CUDA runtime version
    try:
        v = torch.version.cuda
        report.cuda_runtime_version = v
        if v:
            parts = v.split(".")
            major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            report.meets_cuda_version = (major, minor) >= MIN_CUDA_VERSION
    except Exception:  # noqa: BLE001
        report.warnings.append("Could not parse CUDA runtime version.")

    # Driver version
    try:
        drv = torch.cuda.get_driver_version()  # returns int like 59174
        report.driver_version = str(drv)
        if drv < MIN_DRIVER_VERSION * 100:
            report.warnings.append(
                f"Driver {drv} is older than the minimum recommended build "
                f"{MIN_DRIVER_VERSION * 100}.  Update NVIDIA drivers."
            )
    except Exception:  # noqa: BLE001
        pass

    # Enumerate devices
    report.device_count = torch.cuda.device_count()
    for idx in range(report.device_count):
        try:
            props = torch.cuda.get_device_properties(idx)
            vram_mib = props.total_memory // (1024 * 1024)
            dev = DeviceInfo(
                index=idx,
                name=props.name,
                vram_mib=vram_mib,
                compute_capability=(props.major, props.minor),
                is_primary=(idx == 0),
            )
            report.devices.append(dev)
            if idx == 0:
                report.primary_device = dev
        except Exception as exc:  # noqa: BLE001
            report.warnings.append(f"Could not query device {idx}: {exc}")

    # VRAM verdicts (based on primary device)
    if report.primary_device:
        report.meets_min_vram = report.primary_device.vram_mib >= MIN_VRAM_MiB
        report.meets_recommended_vram = report.primary_device.vram_mib >= RECOMMENDED_VRAM_MiB
        if not report.meets_min_vram:
            report.warnings.append(
                f"Primary GPU has only {report.primary_device.vram_gib:.1f} GiB VRAM "
                f"(minimum {MIN_VRAM_MiB // 1024} GiB required)."
            )

    # TensorRT
    try:
        import tensorrt  # type: ignore[import]  # noqa: F401
        report.trt_available = True
    except ImportError:
        pass  # optional — not required for PyTorch inference

    if not report.meets_cuda_version:
        report.warnings.append(
            f"CUDA {report.cuda_runtime_version} is older than the minimum "
            f"{MIN_CUDA_VERSION[0]}.{MIN_CUDA_VERSION[1]}."
        )

    log.debug("NVIDIA compatibility: %s", report.summary())
    return report


# ---------------------------------------------------------------------------
# Convenience singleton (cached after the first call)
# ---------------------------------------------------------------------------
_cached: CompatibilityReport | None = None


def get_cached_report(*, refresh: bool = False) -> CompatibilityReport:
    """Return the cached report, computing it on the first call."""
    global _cached
    if _cached is None or refresh:
        _cached = check_compatibility()
    return _cached
