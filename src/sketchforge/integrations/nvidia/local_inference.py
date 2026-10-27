"""Compatibility exports for the local NVIDIA inference runtime."""
from sketchforge.models.component_detector.inference import (
    Detection,
    InferenceError,
    InferenceResult,
    LocalInferenceSession,
    LocalRuntimeUnavailable,
    _resolve_checkpoint,
    run_local_inference,
)

__all__ = [
    "Detection", "InferenceError", "InferenceResult", "LocalInferenceSession",
    "LocalRuntimeUnavailable", "_resolve_checkpoint", "run_local_inference",
]
