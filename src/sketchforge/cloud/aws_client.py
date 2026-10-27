"""AWS Lambda client for offloading sketch processing to the cloud.

Usage
-----
Activated by the ``--cloud-aws`` CLI flag (wired in ``__main__.py``) or programmatically::

    from sketchforge.cloud.aws_client import AWSSketchClient

    client = AWSSketchClient(endpoint="https://<api-id>.execute-api.<region>.amazonaws.com/production")
    result = client.process_image_file("rough_mobile_ux.jpg")
    doc = result.design_document   # sketchforge.design_ir.schema.DesignDocument

Configuration
-------------
The endpoint URL is resolved in this order (highest priority first):

1. ``endpoint`` constructor argument.
2. ``SKETCHFORGE_AWS_ENDPOINT`` environment variable.
3. ``SKETCHFORGE_AWS_STACK_NAME`` + ``AWS_DEFAULT_REGION`` → queried live from CloudFormation
   outputs using ``boto3`` (optional dependency; only needed for auto-discovery).

The client deliberately has **no** hard dependency on ``boto3`` or ``awscli``; those are
optional — the endpoint URL is always usable directly.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import from_dict
from sketchforge.exceptions import SketchForgeError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------
#: Default request timeout for the /process call (seconds).
DEFAULT_TIMEOUT_S: int = 60

#: Maximum image size sent to Lambda (20 MB; matches the Lambda-side guard).
MAX_IMAGE_BYTES: int = 20 * 1024 * 1024

#: CloudFormation output key that stores the API base URL.
_CFN_OUTPUT_KEY = "ApiEndpoint"

#: Environment variable name that can override the endpoint URL.
_ENV_ENDPOINT = "SKETCHFORGE_AWS_ENDPOINT"

#: Environment variable that names the CloudFormation stack to auto-discover.
_ENV_STACK_NAME = "SKETCHFORGE_AWS_STACK_NAME"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AWSProcessResult:
    """Structured response from the SketchForge AWS Lambda endpoint."""

    design_document: DesignDocument
    """The fully validated Design IR document."""

    notes: list[str] = field(default_factory=list)
    """Pipeline notes / warnings returned by the Lambda."""

    timings_ms: dict[str, float] = field(default_factory=dict)
    """Per-stage latencies reported by the Lambda (e.g. {"preprocess": 45.1, …})."""

    latency_ms: float = 0.0
    """Round-trip network + Lambda execution time measured by this client."""

    pipeline_version: str = "opencv5"
    """Pipeline version string returned by the server."""

    request_id: str = ""
    """AWS Lambda request ID for tracing in CloudWatch."""


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class AWSClientError(SketchForgeError):
    """Raised when the AWS endpoint returns an error or the request fails."""

    def __init__(self, message: str, status_code: int | None = None, server_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.server_code = server_code


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AWSSketchClient:
    """HTTP client that forwards sketch images to the SketchForge AWS Lambda endpoint.

    Parameters
    ----------
    endpoint:
        Base URL of the deployed API Gateway stage, e.g.
        ``"https://abc123.execute-api.us-east-1.amazonaws.com/production"``.
        If *None*, the value is read from the environment or queried from CloudFormation.
    timeout:
        Request timeout in seconds (default: :data:`DEFAULT_TIMEOUT_S`).
    verify_ssl:
        Whether to verify the server's TLS certificate (default: *True*).
        Set to *False* only during local testing with SAM local.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        timeout: int = DEFAULT_TIMEOUT_S,
        verify_ssl: bool = True,
    ) -> None:
        self._endpoint = (endpoint or os.environ.get(_ENV_ENDPOINT) or "").rstrip("/")
        self._timeout = timeout
        self._verify_ssl = verify_ssl

        if not self._endpoint:
            self._endpoint = self._discover_endpoint()

        if not self._endpoint:
            raise AWSClientError(
                "No AWS endpoint configured. "
                f"Set the {_ENV_ENDPOINT!r} environment variable or pass endpoint= to AWSSketchClient()."
            )

        self._process_url = f"{self._endpoint}/process"
        self._health_url = f"{self._endpoint}/health"
        logger.info("AWSSketchClient initialised → %s", self._process_url)

    # ------------------------------------------------------------------
    # Auto-discovery
    # ------------------------------------------------------------------

    def _discover_endpoint(self) -> str:
        """Try to resolve the endpoint from a deployed CloudFormation stack."""
        stack_name = os.environ.get(_ENV_STACK_NAME, "")
        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION", "us-east-1")
        if not stack_name:
            return ""
        try:
            import boto3  # optional dependency
            cf = boto3.client("cloudformation", region_name=region)
            resp = cf.describe_stacks(StackName=stack_name)
            outputs = resp["Stacks"][0].get("Outputs", [])
            for out in outputs:
                if out["OutputKey"] == _CFN_OUTPUT_KEY:
                    url = out["OutputValue"].rstrip("/")
                    logger.info("Auto-discovered endpoint from CFN stack %r: %s", stack_name, url)
                    return url
        except Exception as exc:  # boto3 not installed or stack not found
            logger.debug("CloudFormation auto-discovery failed: %s", exc)
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Return *True* if the Lambda endpoint is healthy (GET /health → 200)."""
        try:
            req = urllib.request.Request(self._health_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                return resp.status == 200
        except Exception as exc:
            logger.warning("Health check failed: %s", exc)
            return False

    def process_image_bytes(
        self,
        image_bytes: bytes,
        *,
        filename: str = "sketch.jpg",
    ) -> AWSProcessResult:
        """Send raw image bytes to the Lambda and return the parsed Design IR.

        Parameters
        ----------
        image_bytes:
            Raw JPEG, PNG, WEBP, or BMP bytes.
        filename:
            Hint for the server log (not functionally significant).

        Returns
        -------
        AWSProcessResult
            Parsed and validated response from the Lambda.

        Raises
        ------
        AWSClientError
            On network errors, HTTP errors, or malformed server responses.
        """
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise AWSClientError(
                f"Image is {len(image_bytes) / 1_048_576:.1f} MB, "
                f"exceeding the {MAX_IMAGE_BYTES // 1_048_576} MB limit."
            )

        payload = json.dumps(
            {"image_b64": base64.b64encode(image_bytes).decode("ascii"), "filename": filename},
            ensure_ascii=True,
        ).encode("ascii")

        req = urllib.request.Request(
            self._process_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-SketchForge-Client": "python-aws-client/1.0",
            },
        )

        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                raw = resp.read()
                latency_ms = (time.perf_counter() - t0) * 1000.0
                status_code = resp.status
        except urllib.error.HTTPError as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            body_text = ""
            with contextlib.suppress(Exception):
                body_text = exc.read().decode("utf-8", errors="replace")
            self._raise_from_body(body_text, exc.code)
        except urllib.error.URLError as exc:
            raise AWSClientError(
                f"Network error contacting {self._process_url}: {exc.reason}"
            ) from exc

        return self._parse_response(raw, status_code, latency_ms)

    def process_image_file(self, path: str | Path) -> AWSProcessResult:
        """Convenience wrapper: read a file from disk and call :meth:`process_image_bytes`.

        Parameters
        ----------
        path:
            Path to a JPEG, PNG, WEBP, or BMP sketch photo.

        Returns
        -------
        AWSProcessResult
        """
        path = Path(path)
        if not path.is_file():
            raise AWSClientError(f"File not found: {path}")
        image_bytes = path.read_bytes()
        logger.info("Processing %s (%d KB) via AWS Lambda…", path.name, len(image_bytes) // 1024)
        return self.process_image_bytes(image_bytes, filename=path.name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_response(
        self, raw: bytes, status_code: int, latency_ms: float
    ) -> AWSProcessResult:
        try:
            body: dict[str, Any] = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AWSClientError(
                f"Lambda returned non-JSON body (HTTP {status_code}): {raw[:200]!r}"
            ) from exc

        if not body.get("ok", False):
            self._raise_from_body_dict(body, status_code)

        ir_dict = body.get("design_ir")
        if not ir_dict:
            raise AWSClientError("Lambda response missing 'design_ir' field.")

        try:
            doc = from_dict(ir_dict)
        except Exception as exc:
            raise AWSClientError(f"Could not parse Design IR from Lambda response: {exc}") from exc

        return AWSProcessResult(
            design_document=doc,
            notes=body.get("notes", []),
            timings_ms=body.get("timings_ms", {}),
            latency_ms=latency_ms,
            pipeline_version=body.get("pipeline_version", "opencv5"),
            request_id=body.get("request_id", ""),
        )

    def _raise_from_body(self, body_text: str, status_code: int) -> None:
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise AWSClientError(
                f"Lambda returned HTTP {status_code}: {body_text[:300]}", status_code=status_code
            ) from exc
        self._raise_from_body_dict(body, status_code)

    @staticmethod
    def _raise_from_body_dict(body: dict[str, Any], status_code: int) -> None:
        code = body.get("error", "unknown_error")
        msg = body.get("message", "No message returned by server.")
        raise AWSClientError(
            f"AWS Lambda error [{code}]: {msg}",
            status_code=status_code,
            server_code=code,
        )

    def __repr__(self) -> str:
        return f"AWSSketchClient(endpoint={self._endpoint!r}, timeout={self._timeout}s)"
