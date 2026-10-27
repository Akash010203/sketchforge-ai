"""Standalone HTTP server wrapping the SketchForge AWS Lambda handler.

Provides a live HTTP endpoint (/health and /process) that replicates the AWS API
Gateway HTTP API v2 contract.  Can be deployed directly on AWS App Runner, ECS,
or an EC2 Graviton instance, or run locally for live end-to-end cloud verification.

Usage:
    python deploy/aws/serve_cloud.py --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Add deploy/aws to sys.path so lambda_function can be imported directly
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lambda_function  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sketchforge-cloud-server")


class LambdaHTTPRequestHandler(BaseHTTPRequestHandler):
    """Translates incoming HTTP requests into AWS API Gateway v2 Lambda events."""

    server_version = "SketchForgeCloud/1.0"

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-SketchForge-Client, Authorization")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        event = {
            "version": "2.0",
            "routeKey": "GET /health",
            "rawPath": self.path,
            "rawQueryString": "",
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "requestContext": {
                "http": {
                    "method": "GET",
                    "path": self.path,
                    "protocol": "HTTP/1.1",
                    "sourceIp": self.client_address[0],
                }
            },
            "isBase64Encoded": False,
        }
        self._dispatch_lambda(event)

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        # Body might be UTF-8 string or raw bytes
        try:
            body_str = post_data.decode("utf-8")
            is_b64 = False
        except UnicodeDecodeError:
            import base64
            body_str = base64.b64encode(post_data).decode("ascii")
            is_b64 = True

        event = {
            "version": "2.0",
            "routeKey": f"POST {self.path}",
            "rawPath": self.path,
            "rawQueryString": "",
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "requestContext": {
                "http": {
                    "method": "POST",
                    "path": self.path,
                    "protocol": "HTTP/1.1",
                    "sourceIp": self.client_address[0],
                }
            },
            "body": body_str,
            "isBase64Encoded": is_b64,
        }
        self._dispatch_lambda(event)

    def _dispatch_lambda(self, event: dict) -> None:
        class FakeContext:
            aws_request_id = f"local-{uuid.uuid4().hex[:12]}"

        try:
            response = lambda_function.handler(event, FakeContext())
            status_code = int(response.get("statusCode", 200))
            headers = response.get("headers", {})
            body = response.get("body", "{}")

            self.send_response(status_code)
            self._send_cors_headers()
            for k, v in headers.items():
                self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(body.encode("utf-8") if isinstance(body, str) else body)
        except Exception as exc:
            logger.exception("Error executing lambda_function.handler")
            self.send_response(500)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err_body = json.dumps({"ok": False, "error": "server_error", "message": str(exc)})
            self.wfile.write(err_body.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        logger.info("%s - %s", self.client_address[0], format % args)


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, LambdaHTTPRequestHandler)
    arch = platform.machine()
    logger.info("SketchForge Cloud Server running on http://%s:%d (Arch: %s)", host, port, arch)
    logger.info("Endpoints available:")
    logger.info("  GET  http://%s:%d/health", host, port)
    logger.info("  POST http://%s:%d/process", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down cloud server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SketchForge Cloud Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
