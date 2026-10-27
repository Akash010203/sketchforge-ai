"""NVIDIA local inference runtime: PyTorch GPU inference wrappers.

This module bridges SketchForge's own trained local models with the NVIDIA
GPU on the host machine.  It does **not** call any remote service — every
computation happens in-process on the local CUDA device.

Responsibilities
----------------
* Lazy-load a trained checkpoint from ``checkpoints/`` without importing
  torch at module-import time (so the application starts even when torch
  is absent).
* Run the locally trained component detector and (eventually) ``LayoutModel`` in
  ``torch.no_grad()`` mode on the best available device.
* Expose a uniform :class:`LocalInferenceSession` object that callers can
  use without knowing about tensors or model internals.
* Time every call and expose the measurement in a :class:`InferenceResult`.
* Report a ``LocalRuntimeUnavailable`` error (not a crash) when the
  checkpoint or PyTorch is missing.

Architecture constraint
-----------------------
This module is an **in-process** computation path, not a network call.
It must never open a socket or call external APIs.  The Nebius remote path
lives in ``integrations/nebius/`` and is separate.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sketchforge.exceptions import SketchForgeError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LocalRuntimeUnavailable(SketchForgeError):
    """Raised when PyTorch is not installed, or no checkpoint is found."""


class InferenceError(SketchForgeError):
    """Raised when inference fails in a recoverable way."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    """One component detection (mirrors the vision pipeline's region proposals)."""
    label: str
    confidence: float
    # All coordinates are normalised to [0, 1] relative to the image
    cx: float
    cy: float
    w: float
    h: float

    def pixel_box(self, img_w: int, img_h: int) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) in pixels for the given image size."""
        x = int((self.cx - self.w / 2) * img_w)
        y = int((self.cy - self.h / 2) * img_h)
        return x, y, int(self.w * img_w), int(self.h * img_h)


@dataclass
class InferenceResult:
    """Complete output of one local inference call."""
    model_name: str
    device: str
    detections: list[Detection] = field(default_factory=list)
    latency_ms: float = 0.0
    checkpoint_epoch: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "device": self.device,
            "detections": [
                {
                    "label": d.label,
                    "confidence": round(d.confidence, 4),
                    "cx": round(d.cx, 4),
                    "cy": round(d.cy, 4),
                    "w": round(d.w, 4),
                    "h": round(d.h, 4),
                }
                for d in self.detections
            ],
            "latency_ms": round(self.latency_ms, 2),
            "checkpoint_epoch": self.checkpoint_epoch,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class LocalInferenceSession:
    """Lazy-loaded, GPU-accelerated in-process SketchForge detector session.

    Parameters
    ----------
    checkpoint_path:
        Path to a component-detector checkpoint produced by the training
        pipeline. If ``None``, the module tries
        ``<repo_root>/checkpoints/component_detector_v1/best.pt``, then the
        legacy ``component_detector.pt`` path.
    device:
        ``"auto"`` (default) uses CUDA if available, else CPU.
        ``"cuda"`` / ``"cpu"`` forces a specific device.
    conf_threshold:
        Minimum class score to keep a detection (default 0.30).
    nms_threshold:
        IoU threshold for non-maximum suppression (default 0.50).
    """

    def __init__(
        self,
        checkpoint_path: Path | str | None = None,
        device: str = "auto",
        conf_threshold: float = 0.30,
        nms_threshold: float = 0.50,
    ) -> None:
        self._checkpoint_path = _resolve_checkpoint(checkpoint_path)
        self._device_pref = device
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold

        # Lazy-loaded on first call
        self._model: Any = None
        self._device_str: str = "cpu"
        self._checkpoint_meta: dict = {}

    # ------------------------------------------------------------------ lazy load
    def _load(self) -> None:
        """Import torch and load the checkpoint (idempotent after the first call)."""
        if self._model is not None:
            return

        try:
            import torch  # noqa: F401 - existence check
        except ImportError as exc:
            raise LocalRuntimeUnavailable(
                "PyTorch is not installed.  Run: pip install torch torchvision"
            ) from exc
        try:
            from sketchforge.models.component_detector.architecture import build_model
        except ImportError as exc:
            raise LocalRuntimeUnavailable(
                f"ComponentDetector model module could not be imported: {exc}"
            ) from exc

        if not self._checkpoint_path.exists():
            raise LocalRuntimeUnavailable(
                f"Checkpoint not found at {self._checkpoint_path}.  "
                "Run the training pipeline first: "
                "python scripts/train_component_detector.py"
            )

        device = _resolve_device(self._device_pref)
        ckpt = torch.load(str(self._checkpoint_path), map_location=device)

        num_classes = ckpt.get("config", {}).get("num_classes", 15)
        model = build_model(num_classes=num_classes)
        model.load_state_dict(ckpt["model_state_dict"])
        model.to(device)
        model.eval()

        self._model = model
        self._device_str = str(device)
        self._checkpoint_meta = {
            "epoch": ckpt.get("epoch"),
            "metrics": ckpt.get("metrics", {}),
            "timestamp": ckpt.get("timestamp"),
        }
        log.info(
            "Loaded ComponentDetector checkpoint (epoch %s) on %s",
            self._checkpoint_meta.get("epoch"),
            self._device_str,
        )

    # ------------------------------------------------------------------ public API
    def predict(
        self,
        image: Any,   # numpy uint8 BGR array (H, W, 3) or (H, W)
        image_wh: tuple[int, int] | None = None,
    ) -> InferenceResult:
        """Run the detector on a preprocessed image.

        Parameters
        ----------
        image:
            NumPy array in BGR (OpenCV) or grayscale uint8.
        image_wh:
            (width, height) of the *original* image before any resizing, used
            to project pixel coordinates.  Defaults to the input image size.

        Returns
        -------
        :class:`InferenceResult` — never raises; errors are captured in
        ``result.error``.
        """
        t0 = time.perf_counter()

        try:
            self._load()
        except LocalRuntimeUnavailable as exc:
            return InferenceResult(
                model_name="component_detector",
                device="none",
                error=str(exc),
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        try:
            import numpy as np
            import torch

            from sketchforge.models.component_detector.decoder import decode, nms

            # Preprocess: grayscale ink mask in [0,1]
            arr = np.asarray(image, dtype=np.float32)
            if arr.ndim == 3:
                import cv2
                arr = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
            arr = 1.0 - arr / 255.0          # invert: ink = 1, paper = 0
            arr = _pad_to_square(arr)         # square for the CNN
            tensor = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0)  # (1,1,H,W)
            tensor = tensor.to(torch.device(self._device_str))

            h, w = arr.shape[:2]
            if image_wh is None:
                image_wh = (w, h)

            with torch.no_grad():
                outputs = self._model(tensor)

            if isinstance(outputs, list):
                from sketchforge.training.detection_targets import generate_anchors
                class_logits = torch.cat([level[0][0] for level in outputs], dim=0)
                deltas = torch.cat([level[1][0] for level in outputs], dim=0)
                anchors = generate_anchors(outputs)
                box_preds = torch.cat((
                    anchors[:, :2] + deltas[:, :2] * anchors[:, 2:],
                    anchors[:, 2:] * deltas[:, 2:].clamp(-5, 5).exp(),
                ), dim=1)
            else:
                class_logits = outputs.get("class_logits") if isinstance(outputs, dict) else outputs
                box_preds = outputs.get("box_preds") if isinstance(outputs, dict) else None

            raw = decode(class_logits, box_preds, self.conf_threshold, image_wh)
            raw = nms(raw, iou_threshold=self.nms_threshold)

            detections = [_raw_to_detection(d) for d in raw]
            latency_ms = (time.perf_counter() - t0) * 1000
            log.debug(
                "LocalInferenceSession.predict: %d detections in %.1f ms on %s",
                len(detections), latency_ms, self._device_str,
            )
            return InferenceResult(
                model_name="component_detector",
                device=self._device_str,
                detections=detections,
                latency_ms=latency_ms,
                checkpoint_epoch=self._checkpoint_meta.get("epoch"),
            )

        except Exception as exc:  # noqa: BLE001
            log.exception("LocalInferenceSession.predict failed")
            return InferenceResult(
                model_name="component_detector",
                device=self._device_str,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    def warmup(self) -> float:
        """Run one dummy forward pass to warm up CUDA kernels.

        Returns the warmup latency in milliseconds, or -1.0 if unavailable.
        """
        try:
            import numpy as np
            dummy = np.zeros((512, 512), dtype=np.uint8)
            result = self.predict(dummy, image_wh=(512, 512))
            return result.latency_ms
        except Exception:  # noqa: BLE001
            return -1.0

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str:
        return self._device_str

    @property
    def checkpoint_meta(self) -> dict:
        return dict(self._checkpoint_meta)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_checkpoint(path: Path | str | None) -> Path:
    if path is not None:
        return Path(path)
    from sketchforge.utilities.paths import repo_root
    root = repo_root() / "checkpoints"
    candidates = (
        root / "component_detector_v1" / "best.pt",
        root / "component_detector.pt",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _resolve_device(pref: str) -> Any:
    import torch
    if pref == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    elif pref == "cuda" and not torch.cuda.is_available():
        name = "cpu"  # silent fallback to CPU when CUDA was requested but not available
    else:
        name = pref
    return torch.device(name)


def _pad_to_square(arr: Any) -> Any:
    """Pad a 2-D float32 array to a square with zeros (paper colour)."""
    import numpy as np
    h, w = arr.shape[:2]
    if h == w:
        return arr
    side = max(h, w)
    out = np.zeros((side, side), dtype=arr.dtype)
    out[:h, :w] = arr
    return out


def _raw_to_detection(raw: Any) -> Detection:
    """Convert a decoder output object/tuple to a :class:`Detection`."""
    # The decoder returns objects with .label/.score/.cx/.cy/.w/.h attributes
    # or namedtuples — handle both gracefully.
    if isinstance(raw, dict):
        return Detection(
            label=raw.get("label", "unknown"),
            confidence=float(raw.get("score", raw.get("confidence", 0.0))),
            cx=float(raw.get("cx", 0.0)),
            cy=float(raw.get("cy", 0.0)),
            w=float(raw.get("w", 0.0)),
            h=float(raw.get("h", 0.0)),
        )
    return Detection(
        label=getattr(raw, "label", "unknown"),
        confidence=float(getattr(raw, "score", getattr(raw, "confidence", 0.0))),
        cx=float(getattr(raw, "cx", 0.0)),
        cy=float(getattr(raw, "cy", 0.0)),
        w=float(getattr(raw, "w", 0.0)),
        h=float(getattr(raw, "h", 0.0)),
    )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def run_local_inference(
    image: Any,
    *,
    checkpoint_path: Path | str | None = None,
    device: str = "auto",
    conf_threshold: float = 0.30,
    nms_threshold: float = 0.50,
    image_wh: tuple[int, int] | None = None,
) -> InferenceResult:
    """One-shot inference helper — creates a session, runs predict, returns result.

    For repeated use, construct a :class:`LocalInferenceSession` instead to
    avoid reloading the checkpoint on every call.
    """
    session = LocalInferenceSession(
        checkpoint_path=checkpoint_path,
        device=device,
        conf_threshold=conf_threshold,
        nms_threshold=nms_threshold,
    )
    return session.predict(image, image_wh=image_wh)
