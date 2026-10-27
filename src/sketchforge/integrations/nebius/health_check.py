"""Connectivity and capability check, run explicitly by the user (``scripts/verify_nebius.py``).

Checks, in order: credentials present → service reachable (model list) → default model listed →
one tiny completion. It sends only a fixed one-line prompt, never design or sketch content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sketchforge.integrations.nebius.model_registry import parse_models
from sketchforge.integrations.provider_interface import (
    ChatMessage,
    CompletionRequest,
    HealthStatus,
    ProviderError,
)

if TYPE_CHECKING:
    from sketchforge.integrations.nebius.client import NebiusClient

PROBE_PROMPT = "Reply with the single word: ok"


def run_health_check(client: NebiusClient) -> HealthStatus:
    checks: dict[str, bool] = {}
    model = client.config.default_model
    t0 = client._clock()  # noqa: SLF001 - same clock the client uses for latency
    try:
        client.config.api_key(client._environ)  # noqa: SLF001
        checks["credentials"] = True
        models = parse_models(client.list_models())
        checks["reachable"] = True
        seen = tuple(m.model_id for m in models)
        checks["model_listed"] = model in seen
        probe = client.complete(CompletionRequest(
            messages=(ChatMessage("user", PROBE_PROMPT),), purpose="health_check", max_tokens=8))
        checks["completion"] = bool(probe.text.strip())
    except ProviderError as err:
        checks.setdefault("credentials", False)
        checks.setdefault("reachable", False)
        return HealthStatus(False, client.name, str(err), model, checks.get("model_listed"),
                            (client._clock() - t0) * 1000, (), checks)  # noqa: SLF001
    ok = all(checks.values())
    return HealthStatus(ok, client.name, "all checks passed" if ok else "some checks failed", model,
                        checks["model_listed"], (client._clock() - t0) * 1000, seen, checks)  # noqa: SLF001
