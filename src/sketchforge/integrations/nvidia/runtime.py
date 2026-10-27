"""NVIDIA local runtime: initialise, warm up, benchmark, and manage the local GPU session.

This module is the *orchestration* layer on top of :mod:`local_inference` and
:mod:`compatibility`.  Its job is:

1. **Initialise** the runtime: run compatibility checks, select the right
   device, load the checkpoint (lazy).
2. **Warm up** CUDA kernels so the first real inference call is not penalised
   by JIT compilation delay.
3. **Benchmark** local throughput and report it alongside the Nebius remote
   path so the application can choose intelligently.
4. **Expose** a :class:`RuntimeStatus` summary the UI and settings dialog can
   display without importing torch.

Architecture constraints
------------------------
* Pure local computation — no sockets, no HTTP.
* Deferred torch import — the application starts even when PyTorch is absent.
* Thread-safe initialisation via a simple lock.
* All timing is wall-clock (``time.perf_counter``), never GPU synchronised
  time, to keep the dependency surface minimal.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status types
# ---------------------------------------------------------------------------


@dataclass
class RuntimeStatus:
    """Snapshot of the NVIDIA local runtime state."""
    initialised: bool = False
    device: str = "none"
    gpu_name: str | None = None
    vram_mib: int | None = None
    cuda_version: str | None = None
    checkpoint_loaded: bool = False
    checkpoint_epoch: int | None = None
    warmup_latency_ms: float | None = None

    # Benchmark results (populated after :meth:`NvidiaRuntime.benchmark`)
    benchmark_latency_ms: float | None = None
    benchmark_throughput_fps: float | None = None

    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.initialised and self.error is None

    def to_dict(self) -> dict:
        return {
            "initialised": self.initialised,
            "device": self.device,
            "gpu_name": self.gpu_name,
            "vram_mib": self.vram_mib,
            "cuda_version": self.cuda_version,
            "checkpoint_loaded": self.checkpoint_loaded,
            "checkpoint_epoch": self.checkpoint_epoch,
            "warmup_latency_ms": (
                round(self.warmup_latency_ms, 2) if self.warmup_latency_ms is not None else None
            ),
            "benchmark_latency_ms": (
                round(self.benchmark_latency_ms, 2)
                if self.benchmark_latency_ms is not None
                else None
            ),
            "benchmark_throughput_fps": (
                round(self.benchmark_throughput_fps, 2)
                if self.benchmark_throughput_fps is not None
                else None
            ),
            "error": self.error,
            "ok": self.ok,
        }

    def summary(self) -> str:
        if not self.initialised:
            return f"not initialised{': ' + self.error if self.error else ''}"
        parts = [self.device]
        if self.gpu_name:
            parts.append(self.gpu_name)
        if self.vram_mib:
            parts.append(f"{self.vram_mib // 1024} GiB VRAM")
        if self.warmup_latency_ms is not None:
            parts.append(f"warmup {self.warmup_latency_ms:.0f} ms")
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Runtime class
# ---------------------------------------------------------------------------


class NvidiaRuntime:
    """Manages the lifecycle of the local NVIDIA GPU inference session.

    Typical usage::

        runtime = NvidiaRuntime()
        runtime.initialise()               # run compatibility checks + warmup
        result = runtime.predict(image)    # fast after warmup
        print(runtime.status.summary())

    The runtime is safe to construct even when PyTorch is absent — all heavy
    imports are deferred until :meth:`initialise` is called.
    """

    def __init__(
        self,
        checkpoint_path: Path | str | None = None,
        device: str = "auto",
        conf_threshold: float = 0.30,
        nms_threshold: float = 0.50,
        run_warmup: bool = True,
        warmup_size: int = 512,
    ) -> None:
        self._checkpoint_path = checkpoint_path
        self._device_pref = device
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self._run_warmup = run_warmup
        self._warmup_size = warmup_size

        self._session: Any = None   # LocalInferenceSession, set in initialise()
        self._status = RuntimeStatus()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def initialise(self, *, force: bool = False) -> RuntimeStatus:
        """Run compatibility checks, load the checkpoint, and optionally warm up.

        Idempotent — a second call is a no-op unless ``force=True``.

        Returns
        -------
        :class:`RuntimeStatus` — inspect ``.ok`` to check success.
        """
        with self._lock:
            if self._status.initialised and not force:
                return self._status

            self._status = RuntimeStatus()
            try:
                self._status = self._do_initialise()
            except Exception as exc:  # noqa: BLE001
                log.exception("NvidiaRuntime.initialise failed unexpectedly")
                self._status.error = f"{type(exc).__name__}: {exc}"
            return self._status

    def predict(self, image: Any, image_wh: tuple[int, int] | None = None) -> Any:
        """Run inference, auto-initialising if needed.

        Returns a :class:`~local_inference.InferenceResult`.
        """
        if not self._status.initialised:
            self.initialise()

        if self._session is None:
            from sketchforge.integrations.nvidia.local_inference import InferenceResult
            return InferenceResult(
                model_name="component_detector",
                device="none",
                error=self._status.error or "runtime not available",
            )
        return self._session.predict(image, image_wh=image_wh)

    def benchmark(self, n_images: int = 10, image_size: int = 512) -> RuntimeStatus:
        """Run *n_images* dummy predictions and record throughput.

        Updates :attr:`status` in place and returns it.
        """
        if not self._status.initialised:
            self.initialise()

        if self._session is None:
            return self._status

        try:
            import numpy as np
            dummy = np.zeros((image_size, image_size), dtype=np.uint8)
            # Discard first run (warmup cache miss)
            self._session.predict(dummy, image_wh=(image_size, image_size))

            t0 = time.perf_counter()
            for _ in range(n_images):
                self._session.predict(dummy, image_wh=(image_size, image_size))
            elapsed = time.perf_counter() - t0

            latency_ms = elapsed / n_images * 1000
            fps = n_images / elapsed
            self._status.benchmark_latency_ms = latency_ms
            self._status.benchmark_throughput_fps = fps
            log.info(
                "NvidiaRuntime benchmark: %.1f ms/image, %.1f fps (%d images, %d px²)",
                latency_ms, fps, n_images, image_size,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("NvidiaRuntime.benchmark failed: %s", exc)
            self._status.benchmark_latency_ms = None

        return self._status

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    @property
    def is_available(self) -> bool:
        """True when the runtime is initialised and has a loaded model."""
        return self._status.initialised and self._session is not None

    # ------------------------------------------------------------------ internal
    def _do_initialise(self) -> RuntimeStatus:
        status = RuntimeStatus()

        # --- compatibility check -----------------------------------------
        from sketchforge.integrations.nvidia.compatibility import check_compatibility
        compat = check_compatibility()

        status.cuda_version = compat.cuda_runtime_version
        if compat.primary_device:
            status.gpu_name = compat.primary_device.name
            status.vram_mib = compat.primary_device.vram_mib

        if not compat.torch_available:
            status.error = "PyTorch is not installed."
            status.initialised = True        # initialised, but unavailable
            return status

        # Choose device string
        if self._device_pref == "auto":
            status.device = "cuda" if compat.cuda_available else "cpu"
        else:
            status.device = self._device_pref

        if not compat.cuda_available and status.device == "cuda":
            status.device = "cpu"
            log.warning(
                "Requested CUDA device but CUDA is not available; falling back to CPU."
            )

        # --- session -----------------------------------------------------
        from sketchforge.integrations.nvidia.local_inference import LocalInferenceSession
        session = LocalInferenceSession(
            checkpoint_path=self._checkpoint_path,
            device=status.device,
            conf_threshold=self.conf_threshold,
            nms_threshold=self.nms_threshold,
        )

        # Try loading the checkpoint (this is where LocalRuntimeUnavailable may fire)
        from sketchforge.integrations.nvidia.local_inference import LocalRuntimeUnavailable
        try:
            session._load()  # noqa: SLF001 — explicit pre-load for status reporting
            status.checkpoint_loaded = True
            status.checkpoint_epoch = session.checkpoint_meta.get("epoch")
        except LocalRuntimeUnavailable as exc:
            # Not fatal — we can still report the status; predict() will fail gracefully
            log.warning("NvidiaRuntime: checkpoint not available: %s", exc)
            status.error = str(exc)
            status.initialised = True
            return status

        self._session = session

        # --- warmup ------------------------------------------------------
        if self._run_warmup:
            warmup_ms = session.warmup()
            if warmup_ms >= 0:
                status.warmup_latency_ms = warmup_ms
                log.info(
                    "NvidiaRuntime warmup: %.1f ms on %s", warmup_ms, status.device
                )

        status.initialised = True
        return status


# ---------------------------------------------------------------------------
# Module-level default runtime (singleton pattern, created on demand)
# ---------------------------------------------------------------------------

_default_runtime: NvidiaRuntime | None = None
_default_lock = threading.Lock()


def get_runtime(
    *,
    checkpoint_path: Path | str | None = None,
    device: str = "auto",
    auto_init: bool = True,
) -> NvidiaRuntime:
    """Return the default :class:`NvidiaRuntime`, creating it on first access.

    Parameters
    ----------
    checkpoint_path:
        Override the default checkpoint location.
    device:
        ``"auto"`` / ``"cuda"`` / ``"cpu"``.
    auto_init:
        If ``True`` (default), call :meth:`~NvidiaRuntime.initialise`
        automatically before returning.
    """
    global _default_runtime
    with _default_lock:
        if _default_runtime is None:
            _default_runtime = NvidiaRuntime(
                checkpoint_path=checkpoint_path,
                device=device,
            )
            if auto_init:
                _default_runtime.initialise()
    return _default_runtime


def reset_runtime() -> None:
    """Discard the cached default runtime (useful in tests)."""
    global _default_runtime
    with _default_lock:
        _default_runtime = None
