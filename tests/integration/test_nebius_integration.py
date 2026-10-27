"""The Nebius client against an in-process fake transport (no sockets, no network, no key).

These tests prove the *protocol handling*: consent gating, request shape, retries, error mapping,
privacy limits. They say nothing about whether the real service accepts our calls; that is
`scripts/verify_nebius.py`, which needs a key and a networked machine.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

openai = pytest.importorskip("openai")
try:  # the SDK's HTTP layer was renamed in newer releases
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from sketchforge.integrations.nebius import (  # noqa: E402
    ConsentGate,
    NebiusClient,
    NebiusConfig,
    egress_notice,
    load_nebius_config,
)
from sketchforge.integrations.nebius.health_check import run_health_check  # noqa: E402
from sketchforge.integrations.nebius.model_registry import parse_models, pick_model  # noqa: E402
from sketchforge.integrations.provider_interface import (  # noqa: E402
    ChatMessage,
    CompletionRequest,
    ModelProvider,
    PolicyViolation,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderDisabled,
    ProviderTimeout,
    ProviderUnavailable,
)

KEY = "test-key-DO-NOT-LEAK-1234567890"
ENV = {"NEBIUS_API_KEY": KEY}


def ok_body(text='{"ok": true}', *, model="nvidia/Nemotron-3_5-Lightning", finish="stop", prompt=11, completion=7):
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion},
    }


class FakeService:
    """Scripted responses; each item is an httpx.Response, a callable(request), or an Exception."""

    def __init__(self, *script):
        self.script, self.requests = list(script), []

    def __call__(self, request):
        self.requests.append(request)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


def make(service, *, enabled=True, consent=True, environ=ENV, **cfg):
    config = NebiusConfig(enabled=enabled, **cfg)
    gate = ConsentGate()
    if consent:
        gate.acknowledge()
    sleeps: list[float] = []
    client = NebiusClient(config, gate, environ=environ, http_client=service.client(),
                          sleep=sleeps.append, jitter=lambda: 1.0)
    client.sleeps = sleeps
    return client


def req(text="hello", **kw):
    return CompletionRequest((ChatMessage("user", text),), purpose="test", **kw)


def resp(status=200, body=None, headers=None):
    return httpx.Response(status, json=body if body is not None else ok_body(), headers=headers)


# --------------------------------------------------------------------------- gating
def test_disabled_by_default_and_sends_nothing():
    svc = FakeService(resp())
    client = NebiusClient(NebiusConfig(), ConsentGate(), environ=ENV, http_client=svc.client())
    with pytest.raises(ProviderDisabled, match="disabled"):
        client.complete(req())
    assert svc.requests == []


def test_shipped_config_is_disabled_and_never_sends_images_or_text():
    cfg = load_nebius_config()
    assert cfg.enabled is False
    assert cfg.privacy.allow_images is False and cfg.privacy.include_user_text is False
    assert cfg.default_model.startswith("nvidia/")


def test_no_consent_no_request():
    svc = FakeService(resp())
    with pytest.raises(ProviderDisabled, match="acknowledged"):
        make(svc, consent=False).complete(req())
    assert svc.requests == []


def test_revoking_consent_stops_requests():
    svc = FakeService(resp())
    client = make(svc)
    client.complete(req())
    client.consent.revoke()
    with pytest.raises(ProviderDisabled):
        client.complete(req())
    assert len(svc.requests) == 1


def test_missing_key_is_an_auth_error_before_any_request():
    svc = FakeService(resp())
    with pytest.raises(ProviderAuthError, match="NEBIUS_API_KEY"):
        make(svc, environ={}).complete(req())
    assert svc.requests == []


# --------------------------------------------------------------------------- wire format
def test_success_request_shape_and_result():
    svc = FakeService(resp())
    client = make(svc)
    result = client.complete(req("design summary", json_mode=True, max_tokens=300))
    r = svc.requests[0]
    assert r.method == "POST" and str(r.url) == "https://api.tokenfactory.nebius.com/v1/chat/completions"
    assert r.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(r.content)
    assert body["model"] == "nvidia/Nemotron-3_5-Lightning"
    assert body["messages"] == [{"role": "user", "content": "design summary"}]
    assert body["max_tokens"] == 300 and body["temperature"] == 0.0
    assert body["response_format"] == {"type": "json_object"}
    assert result.text == '{"ok": true}' and result.usage.total_tokens == 18 and result.attempts == 1
    assert result.model == "nvidia/Nemotron-3_5-Lightning" and result.latency_ms >= 0


def test_no_response_format_unless_json_mode():
    svc = FakeService(resp())
    make(svc).complete(req())
    assert "response_format" not in json.loads(svc.requests[0].content)


def test_usage_log_records_numbers_not_content_or_key():
    svc = FakeService(resp())
    client = make(svc)
    client.complete(req("SECRET PROMPT TEXT"))
    (rec,) = client.usage_log
    dumped = json.dumps(rec.__dict__)
    assert rec.ok and rec.prompt_tokens == 11 and rec.completion_tokens == 7 and rec.purpose == "test"
    assert rec.prompt_chars == len("SECRET PROMPT TEXT")
    assert "SECRET" not in dumped and KEY not in dumped


# --------------------------------------------------------------------------- retries & errors
def test_rate_limit_is_retried_and_honours_retry_after():
    svc = FakeService(resp(429, {"error": {"message": "slow down"}}, {"retry-after": "3"}), resp())
    client = make(svc, backoff_base_s=0.5, backoff_cap_s=8)
    result = client.complete(req())
    assert result.attempts == 2 and len(svc.requests) == 2
    assert client.sleeps and client.sleeps[0] >= 3.0


def test_retry_after_is_capped():
    svc = FakeService(resp(429, {"error": {"message": "x"}}, {"retry-after": "900"}), resp())
    client = make(svc, backoff_cap_s=5)
    client.complete(req())
    assert client.sleeps[0] <= 5.0


def test_server_errors_exhaust_the_bounded_retries():
    svc = FakeService(resp(503, {"error": {"message": "down"}}))
    client = make(svc, max_retries=2)
    with pytest.raises(ProviderUnavailable):
        client.complete(req())
    assert len(svc.requests) == 3  # 1 + max_retries, never more
    assert len(client.sleeps) == 2
    assert client.usage_log[-1].ok is False and client.usage_log[-1].attempts == 3


def test_backoff_grows_and_is_capped():
    svc = FakeService(resp(500, {"error": {"message": "x"}}))
    client = make(svc, max_retries=4, backoff_base_s=1.0, backoff_cap_s=3.0)
    with pytest.raises(ProviderUnavailable):
        client.complete(req())
    assert client.sleeps == [1.0, 2.0, 3.0, 3.0]  # jitter fixed at its maximum in the test


def test_auth_failure_is_not_retried():
    svc = FakeService(resp(401, {"error": {"message": "bad key"}}))
    with pytest.raises(ProviderAuthError):
        make(svc).complete(req())
    assert len(svc.requests) == 1


def test_bad_request_is_not_retried_and_does_not_leak_the_key():
    svc = FakeService(resp(400, {"error": {"message": "unknown model"}}))
    client = make(svc)
    with pytest.raises(ProviderBadResponse, match="unknown model") as err:
        client.complete(req())
    assert len(svc.requests) == 1 and KEY not in str(err.value)


def test_timeouts_are_retried_then_reported():
    svc = FakeService(httpx.ReadTimeout("slow"))
    client = make(svc, max_retries=1)
    with pytest.raises(ProviderTimeout):
        client.complete(req())
    assert len(svc.requests) == 2


def test_connection_errors_map_to_unavailable():
    svc = FakeService(httpx.ConnectError("no route"))
    with pytest.raises(ProviderUnavailable):
        make(svc, max_retries=0).complete(req())


def test_a_transient_failure_then_success():
    svc = FakeService(httpx.ConnectError("blip"), resp())
    result = make(svc).complete(req())
    assert result.attempts == 2


@pytest.mark.parametrize("body,fragment", [
    (ok_body(text=""), "empty"),
    (ok_body(text='{"a":', finish="length"), "cut off"),
    ({**ok_body(), "choices": []}, "no choices"),
])
def test_unusable_answers_are_rejected_not_retried(body, fragment):
    svc = FakeService(resp(200, body))
    with pytest.raises(ProviderBadResponse, match=fragment):
        make(svc).complete(req())
    assert len(svc.requests) == 1


# --------------------------------------------------------------------------- privacy policy
def test_oversized_prompt_is_refused_locally():
    svc = FakeService(resp())
    client = make(svc, privacy={"max_prompt_chars": 100})
    with pytest.raises(PolicyViolation, match="limit"):
        client.complete(req("x" * 101))
    assert svc.requests == []


@pytest.mark.parametrize("tokens", [0, 5000])
def test_token_budget_is_bounded(tokens):
    with pytest.raises(PolicyViolation):
        make(FakeService(resp())).complete(req(max_tokens=tokens))


def test_egress_notice_is_specific_and_matches_the_configuration():
    notice = egress_notice(NebiusConfig(enabled=True))
    assert "api.tokenfactory.nebius.com" in notice and "NOT sent" in notice
    assert "NOT included" in notice and "retained" in notice and "not used to train" in notice
    permissive = egress_notice(NebiusConfig(enabled=True, privacy={"include_user_text": True, "allow_images": True}))
    assert "IS included" in permissive and "MAY be sent" in permissive


# --------------------------------------------------------------------------- models & health
MODELS_BODY = {"object": "list", "data": [
    {"id": "nvidia/Nemotron-3_5-Lightning", "object": "model", "architecture": {"modality": "text->text"}},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "object": "model"},
    {"id": "meta-llama/Llama-3.3-70B-Instruct", "object": "model", "architecture": {"modality": "text+image->text"}},
]}


def route(request):
    if request.url.path.endswith("/models"):
        assert request.url.params.get("verbose") == "true"
        return resp(200, MODELS_BODY)
    return resp(200, ok_body("ok"))


def test_parse_models_and_capabilities():
    models = parse_models(MODELS_BODY["data"])
    by_id = {m.model_id: m for m in models}
    assert by_id["nvidia/Nemotron-3_5-Lightning"].accepts_images is False
    assert by_id["nvidia/nemotron-3-super-120b-a12b"].accepts_images is None  # unknown, treated as text-only
    assert by_id["meta-llama/Llama-3.3-70B-Instruct"].accepts_images is True
    assert all(m.is_nvidia for m in models if m.model_id.startswith("nvidia/"))
    assert pick_model(models, ["nvidia/missing", "nvidia/nemotron-3-super-120b-a12b"]).model_id.endswith("a12b")
    assert pick_model(models, ["nope"]) is None
    assert parse_models([{"id": ""}, {"nope": 1}, {"id": 5}]) == []


def test_health_check_passes_when_everything_works():
    status = run_health_check(make(FakeService(route)))
    assert status.ok and status.model_available
    assert status.checks == {"credentials": True, "reachable": True, "model_listed": True, "completion": True}
    assert "nvidia/Nemotron-3_5-Lightning" in status.models_seen


def test_health_check_reports_a_missing_model():
    status = run_health_check(make(FakeService(route), default_model="nvidia/not-served"))
    assert not status.ok and status.model_available is False and status.checks["model_listed"] is False


def test_health_check_reports_unreachable_service():
    status = run_health_check(make(FakeService(httpx.ConnectError("blocked")), max_retries=0))
    assert not status.ok and status.checks["reachable"] is False


def test_health_check_without_consent_does_not_touch_the_network():
    svc = FakeService(route)
    status = make(svc, consent=False).health()
    assert not status.ok and svc.requests == []


def test_client_satisfies_the_provider_protocol():
    assert isinstance(make(FakeService(resp())), ModelProvider)


# --------------------------------------------------------------------------- architecture
def test_core_packages_do_not_import_the_integrations():
    """Only `assist/` (via the interface) and scripts may reach providers; the engine stays local."""
    root = Path(__file__).resolve().parents[2] / "src" / "sketchforge"
    offenders = []
    for pkg in ("vision", "layout", "design_ir", "evaluation", "repair", "rendering", "editor", "domain"):
        for path in (root / pkg).rglob("*.py"):
            if "sketchforge.integrations" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_no_module_opens_a_server_socket_or_imports_a_web_framework():
    root = Path(__file__).resolve().parents[2] / "src" / "sketchforge"
    banned = ("fastapi", "flask", "uvicorn", "http.server", "socketserver", "aiohttp.web", "django")
    exempt = {
        Path("ui/web_studio.py"),
        Path("ui/preview_panel.py"),  # local preview HTTP server
        Path("generation/backend_server.py"),
    }
    hits = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative in exempt:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if any(name == item or name.startswith(item + ".") for item in banned):
                    hits.append(f"{relative}:{node.lineno}: {name}")
    assert hits == []
