"""Unit tests for the SketchForge Cloud / AWS subsystem and CLI commands."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sketchforge.__main__ import build_parser, main
from sketchforge.cloud.aws_client import (
    DEFAULT_TIMEOUT_S,
    AWSClientError,
    AWSProcessResult,
    AWSSketchClient,
)
from sketchforge.design_ir import (
    BBox,
    Component,
    ComponentType,
    DesignDocument,
    new_document,
    to_dict,
)


def _make_dummy_doc() -> DesignDocument:
    doc = new_document("test", 800, 600)
    doc.components.append(
        Component(
            id="btn_1",
            type=ComponentType.BUTTON,
            bbox=BBox(x=10, y=10, w=120, h=50),
            text="Submit",
        )
    )
    return doc


def test_aws_client_init_endpoint():
    client = AWSSketchClient(endpoint="https://api.example.com/production/")
    assert client._endpoint == "https://api.example.com/production"
    assert client._process_url == "https://api.example.com/production/process"
    assert client._health_url == "https://api.example.com/production/health"
    assert client._timeout == DEFAULT_TIMEOUT_S
    assert "AWSSketchClient" in repr(client)


def test_aws_client_init_env_var(monkeypatch):
    monkeypatch.setenv("SKETCHFORGE_AWS_ENDPOINT", "https://env-api.example.com")
    client = AWSSketchClient()
    assert client._endpoint == "https://env-api.example.com"


def test_aws_client_init_missing_raises(monkeypatch):
    monkeypatch.delenv("SKETCHFORGE_AWS_ENDPOINT", raising=False)
    monkeypatch.delenv("SKETCHFORGE_AWS_STACK_NAME", raising=False)
    with pytest.raises(AWSClientError, match="No AWS endpoint configured"):
        AWSSketchClient()


def test_aws_client_health_check_true():
    client = AWSSketchClient(endpoint="https://api.example.com")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert client.health_check() is True


def test_aws_client_health_check_false():
    client = AWSSketchClient(endpoint="https://api.example.com")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Failed")):
        assert client.health_check() is False


def test_aws_client_process_image_bytes():
    client = AWSSketchClient(endpoint="https://api.example.com")
    doc = _make_dummy_doc()
    resp_payload = {
        "ok": True,
        "design_ir": to_dict(doc),
        "notes": ["detected 1 button"],
        "timings_ms": {"perspective": 12.0},
        "pipeline_version": "opencv5",
        "request_id": "req-12345",
    }
    resp_bytes = json.dumps(resp_payload).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = resp_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.process_image_bytes(b"dummy_image_data", filename="test.png")

    assert isinstance(res, AWSProcessResult)
    assert any(c.id == "btn_1" for c in res.design_document.components)
    assert res.request_id == "req-12345"
    assert res.notes == ["detected 1 button"]


def test_aws_client_process_image_file(tmp_path):
    img_path = tmp_path / "sample.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0dummy_jpeg")

    client = AWSSketchClient(endpoint="https://api.example.com")
    doc = _make_dummy_doc()
    resp_payload = {
        "ok": True,
        "design_ir": to_dict(doc),
        "notes": [],
        "timings_ms": {},
    }
    resp_bytes = json.dumps(resp_payload).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = resp_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.process_image_file(img_path)

    assert any(c.id == "btn_1" for c in res.design_document.components)


def test_aws_client_error_response():
    client = AWSSketchClient(endpoint="https://api.example.com")
    err_body = json.dumps({"ok": False, "error": "invalid_image", "message": "Corrupt file"}).encode("utf-8")

    err = urllib.error.HTTPError(
        url="https://api.example.com/process",
        code=422,
        msg="Unprocessable Entity",
        hdrs={},
        fp=io.BytesIO(err_body),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(AWSClientError, match=r"\[invalid_image\]: Corrupt file") as exc_info:
            client.process_image_bytes(b"bad_bytes")
        assert exc_info.value.status_code == 422


def test_cli_parser_cloud_subcommand():
    parser = build_parser()
    args = parser.parse_args(["cloud", "--image", "sample.png", "--endpoint", "https://api.example.com"])
    assert args.command == "cloud"
    assert args.image == "sample.png"
    assert args.endpoint == "https://api.example.com"
    assert args.cloud_aws is True


def test_cli_main_cloud_aws_shortcut(tmp_path, monkeypatch):
    img_path = tmp_path / "sketch.png"
    img_path.write_bytes(b"sketch_bytes")
    out_dir = tmp_path / "out"

    doc = _make_dummy_doc()
    fake_result = AWSProcessResult(
        design_document=doc,
        notes=["all good"],
        timings_ms={"cv": 5.0},
        latency_ms=100.0,
        pipeline_version="opencv5",
        request_id="test-req",
    )

    with patch("sketchforge.cloud.aws_client.AWSSketchClient.health_check", return_value=True), \
         patch("sketchforge.cloud.aws_client.AWSSketchClient.process_image_file", return_value=fake_result):
        # Calling with --cloud-aws shortcut
        code = main([
            "--cloud-aws",
            "--image", str(img_path),
            "--endpoint", "https://api.example.com",
            "--out", str(out_dir),
        ])
        assert code == 0

    saved_ir = out_dir / f"{img_path.stem}_design_ir.json"
    assert saved_ir.is_file()
    saved_data = json.loads(saved_ir.read_text(encoding="utf-8"))
    assert any(c["id"] == "btn_1" for c in saved_data["components"])


def test_lambda_handler_health_check():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy" / "aws"))
    import lambda_function

    event = {
        "rawPath": "/health",
        "requestContext": {"http": {"method": "GET"}},
    }
    resp = lambda_function.handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert body["status"] in ("ok", "healthy")
    assert body["opencv_version"] == "5.0.0"
    assert body["region"] == "aws-lambda"
