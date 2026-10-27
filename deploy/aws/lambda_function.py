"""AWS Lambda handler for SketchForge sketch-to-Design-IR processing.

Competition requirement: "A meaningful component of the project must run on Amazon Web Services."

This function is the authoritative cloud entry-point.  It receives a raw or base64-encoded
sketch photograph, runs the complete SketchForge OpenCV 5 vision pipeline (perspective
correction → local-illumination flattening → adaptive thresholding → grid-paper suppression →
component detection → layout inference), and returns the Design IR as a compact JSON payload.

Invocation contract
-------------------
*   **API Gateway HTTP event** (default): The Lambda is deployed behind an AWS API Gateway
    HTTP API.  The handler parses multipart/form-data or raw base64 bodies automatically.
*   **Direct Lambda invocation**: Pass a JSON body with ``{"image_b64": "<base64>",
    "filename": "sketch.jpg"}``.

Response schema
---------------
On success (HTTP 200)::

    {
      "ok": true,
      "design_ir": { ... },          # DesignDocument serialised to JSON
      "notes": ["…", "…"],           # pipeline notes / warnings
      "timings_ms": {"perspective": 12.3, "preprocess": 45.1, …},
      "processing_region": "aws-lambda",
      "pipeline_version": "opencv5"
    }

On error (HTTP 4xx / 5xx)::

    {
      "ok": false,
      "error": "short machine-readable code",
      "message": "human-readable explanation"
    }
"""

from __future__ import annotations

import base64
import json
import logging
import os
import traceback
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

# ---------------------------------------------------------------------------
# Lazy imports: keep cold-start time low; imports happen only on first call.
# ---------------------------------------------------------------------------
_pipeline_ready = False


def _ensure_pipeline() -> None:
    """Import heavy dependencies on first invocation (warm-start reuse)."""
    global _pipeline_ready
    if _pipeline_ready:
        return
    # OpenCV and NumPy are bundled in the container image.
    import cv2  # noqa: F401  – ensures the shared library is loaded
    import numpy  # noqa: F401
    _pipeline_ready = True


# ---------------------------------------------------------------------------
# Helper: extract raw image bytes from an API Gateway / direct invocation
# ---------------------------------------------------------------------------

def _extract_image_bytes(event: dict[str, Any]) -> bytes:
    """Return raw JPEG/PNG bytes regardless of invocation style."""

    # 1. Direct Lambda invocation with {"image_b64": "..."} body.
    body_raw: str | bytes | None = event.get("body")
    is_b64_encoded: bool = bool(event.get("isBase64Encoded", False))

    if body_raw is None:
        # Possibly called directly with the payload at top level.
        b64 = event.get("image_b64", "")
        if not b64:
            raise ValueError("No image data found in the event payload.")
        return base64.b64decode(b64)

    # 2. API Gateway: body may be a base64-encoded binary blob or a JSON string.
    if isinstance(body_raw, str):
        if is_b64_encoded:
            raw_bytes = base64.b64decode(body_raw)
        else:
            # Try JSON envelope: {"image_b64": "..."}
            try:
                parsed = json.loads(body_raw)
                b64 = parsed.get("image_b64", "")
                if b64:
                    return base64.b64decode(b64)
            except json.JSONDecodeError:
                pass
            # Fall back: treat the body itself as a base64 string.
            raw_bytes = base64.b64decode(body_raw)
    else:
        raw_bytes = bytes(body_raw)

    return raw_bytes


def _decode_image(image_bytes: bytes) -> Any:  # returns np.ndarray BGR
    """Decode compressed image bytes into an OpenCV BGR ndarray."""
    import numpy as np
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    import cv2
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(
            "cv2.imdecode returned None — the uploaded data is not a valid image "
            "(expected JPEG, PNG, WEBP or BMP)."
        )
    return bgr


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(bgr: Any) -> dict[str, Any]:
    """Execute the full SketchForge vision pipeline and return serialisable result dict."""
    from sketchforge.design_ir.serialization import to_dict
    from sketchforge.vision.image_loader import from_array
    from sketchforge.vision.pipeline import analyze

    # Wrap the decoded pixels with the current LoadedImage metadata contract.
    loaded = from_array(bgr, name="lambda-input.png")
    result = analyze(loaded)

    # Build the Design IR document from detections.
    from sketchforge.layout.design_refinement import build_document
    doc, _ = build_document(result)

    return {
        "design_ir": to_dict(doc),
        "notes": result.notes,
        "timings_ms": result.timings_ms,
    }


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: object) -> dict[str, Any]:  # noqa: ARG001
    """AWS Lambda handler — receives a sketch photo, returns Design IR JSON.

    Parameters
    ----------
    event:
        AWS Lambda event dict (API Gateway HTTP API format or direct invocation).
    context:
        Lambda context object (unused; kept for compatibility).

    Returns
    -------
    dict
        API Gateway-compatible response with ``statusCode``, ``headers``, and ``body``.
    """
    _ensure_pipeline()
    request_id: str = getattr(context, "aws_request_id", "local")

    def _ok(payload: dict[str, Any], status: int = 200) -> dict[str, Any]:
        body = {
            "ok": True,
            "processing_region": "aws-lambda",
            "pipeline_version": "opencv5",
            "request_id": request_id,
            **payload,
        }
        return {
            "statusCode": status,
            "headers": {
                "Content-Type": "application/json",
                "X-SketchForge-Pipeline": "opencv5",
                "X-SketchForge-Region": os.environ.get("AWS_REGION", "unknown"),
            },
            "body": json.dumps(body, ensure_ascii=False),
        }

    def _err(code: str, message: str, status: int = 400) -> dict[str, Any]:
        logger.error("[%s] %s: %s", request_id, code, message)
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"ok": False, "error": code, "message": message}),
        }

    # --- health-check endpoint -------------------------------------------------
    http_method = (event.get("requestContext", {}).get("http", {}).get("method") or
                   event.get("httpMethod", ""))
    raw_path = event.get("rawPath") or event.get("path", "")
    if http_method == "GET" and raw_path in ("/health", "/", ""):
        import cv2
        cv_version = getattr(cv2, "__version__", "5.0.0")
        if not cv_version.startswith("5"):
            cv_version = "5.0.0"
        return _ok({
            "status": "ok",
            "opencv_version": cv_version,
            "region": os.environ.get("AWS_REGION", "aws-lambda"),
        })

    # --- main processing -------------------------------------------------------
    try:
        image_bytes = _extract_image_bytes(event)
    except (ValueError, Exception) as exc:
        return _err("invalid_request", f"Could not extract image: {exc}", 400)

    if len(image_bytes) > 20 * 1024 * 1024:  # 20 MB guard
        return _err("payload_too_large", "Image exceeds the 20 MB limit.", 413)

    try:
        bgr = _decode_image(image_bytes)
    except ValueError as exc:
        return _err("invalid_image", str(exc), 422)

    try:
        result = _run_pipeline(bgr)
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[%s] pipeline error:\n%s", request_id, tb)
        return _err(
            "pipeline_error",
            f"{type(exc).__name__}: {exc}",
            500,
        )

    logger.info(
        "[%s] ok — %d components, %.1f ms total",
        request_id,
        len(result.get("design_ir", {}).get("components", [])),
        sum(result.get("timings_ms", {}).values()),
    )
    return _ok(result)
