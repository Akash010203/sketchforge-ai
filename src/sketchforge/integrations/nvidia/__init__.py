"""NVIDIA local GPU integration.

Sub-modules
-----------
compatibility    — CUDA / driver / hardware compatibility checks (no torch import at module level)
local_inference  — In-process ComponentDetector inference on local GPU
runtime          — Session lifecycle: init, warmup, benchmark
model_configuration — Catalogue of eligible NVIDIA model identifiers
"""

from sketchforge.integrations.nvidia.compatibility import (
    CompatibilityReport,
    DeviceInfo,
    check_compatibility,
    get_cached_report,
)
from sketchforge.integrations.nvidia.local_inference import (
    Detection,
    InferenceResult,
    LocalInferenceSession,
    LocalRuntimeUnavailable,
    InferenceError,
    run_local_inference,
)
from sketchforge.integrations.nvidia.runtime import (
    NvidiaRuntime,
    RuntimeStatus,
    get_runtime,
    reset_runtime,
)
from sketchforge.integrations.nvidia.model_configuration import (
    NvidiaModel,
    CATALOGUE,
    find,
    is_nvidia_model,
)

__all__ = [
    # compatibility
    "CompatibilityReport",
    "DeviceInfo",
    "check_compatibility",
    "get_cached_report",
    # local_inference
    "Detection",
    "InferenceResult",
    "LocalInferenceSession",
    "LocalRuntimeUnavailable",
    "InferenceError",
    "run_local_inference",
    # runtime
    "NvidiaRuntime",
    "RuntimeStatus",
    "get_runtime",
    "reset_runtime",
    # model_configuration
    "NvidiaModel",
    "CATALOGUE",
    "find",
    "is_nvidia_model",
]
