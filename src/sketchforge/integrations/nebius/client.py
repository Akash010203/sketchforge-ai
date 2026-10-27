"""Nebius Token Factory client (OpenAI-compatible API) behind the provider interface.

Uses the OpenAI SDK, as the Token Factory documentation does, with a custom ``base_url``. This is
an *outbound* client: SketchForge never listens on a port. The SDK's own retries are disabled; this
module implements the bounded retry policy so behaviour and logging are ours:

* retried: rate limits (honouring Retry-After, capped), timeouts, connection errors, 5xx;
* never retried: authentication/permission errors, bad requests, unusable answers;
* every attempt is timed; a usage record (no prompt or answer text) is kept per request.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

from sketchforge.integrations.nebius.configuration import NebiusConfig
from sketchforge.integrations.nebius.request_policy import ConsentGate, authorize, check_request
from sketchforge.integrations.provider_interface import (
    CompletionRequest,
    CompletionResult,
    HealthStatus,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    Usage,
    UsageRecord,
)

log = logging.getLogger(__name__)
_MAX_ERROR_CHARS = 240


def _short(text: object) -> str:
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= _MAX_ERROR_CHARS else one_line[:_MAX_ERROR_CHARS] + "…"


class NebiusClient:
    name = "nebius"

    def __init__(
        self,
        config: NebiusConfig,
        consent: ConsentGate | None = None,
        *,
        environ: dict[str, str] | None = None,
        http_client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self.consent = consent or ConsentGate()
        self._environ = environ
        self._http_client = http_client
        self._sleep, self._clock, self._jitter = sleep, clock, jitter
        self._usage: list[UsageRecord] = []
        self._sdk_cache: Any | None = None

    # ------------------------------------------------------------------ SDK access
    def _sdk(self) -> Any:
        if self._sdk_cache is None:
            try:
                import openai
            except ImportError as exc:
                raise ProviderUnavailable(
                    "the 'openai' package is not installed; run: pip install 'sketchforge[remote]'") from exc
            self._sdk_cache = openai.OpenAI(
                api_key=self.config.api_key(self._environ), base_url=self.config.base_url,
                timeout=self.config.timeout_s, max_retries=0, http_client=self._http_client)
        return self._sdk_cache

    def _translate(self, exc: Exception) -> ProviderError:
        """Map an SDK exception onto the provider error family (nothing SDK-specific escapes)."""
        import openai

        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return ProviderAuthError(f"the service rejected the credentials ({_short(exc)})")
        if isinstance(exc, openai.RateLimitError):
            retry_after = None
            headers = getattr(getattr(exc, "response", None), "headers", None)
            try:
                retry_after = float(headers.get("retry-after")) if headers and headers.get("retry-after") else None
            except (TypeError, ValueError):
                retry_after = None
            return ProviderRateLimited("rate limited by the service", retry_after)
        if isinstance(exc, openai.APITimeoutError):
            return ProviderTimeout(f"no answer within {self.config.timeout_s:g} s")
        if isinstance(exc, openai.APIConnectionError):
            return ProviderUnavailable(f"could not reach the service ({_short(exc)})")
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and status >= 500:
            return ProviderUnavailable(f"service error {status}")
        if isinstance(exc, openai.APIStatusError):
            return ProviderBadResponse(f"the service refused the request ({status}): {_short(getattr(exc, 'message', exc))}")
        return ProviderUnavailable(f"unexpected failure talking to the service: {_short(exc)}")

    # ------------------------------------------------------------------ public API
    @property
    def usage_log(self) -> list[UsageRecord]:
        return self._usage

    def complete(self, request: CompletionRequest) -> CompletionResult:
        authorize(self.config, self.consent)
        chars = check_request(self.config, request)
        model = request.model or self.config.default_model
        sdk = self._sdk()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        attempts = self.config.max_retries + 1
        started = self._clock()
        last: ProviderError | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = sdk.chat.completions.create(**kwargs)
                result = self._parse(response, model, attempt, (self._clock() - started) * 1000, request=request)
            except ProviderError as err:  # raised by _parse: not retryable
                last = err
                break
            except Exception as exc:  # noqa: BLE001 - translated into the provider family
                last = self._translate(exc)
                if not last.retryable or attempt == attempts:
                    break
                delay = self._delay(attempt, last)
                log.info("nebius %s attempt %d failed (%s); retrying in %.2fs", request.purpose, attempt, last, delay)
                self._sleep(delay)
                continue
            self._record(request, model, True, result.latency_ms, result.usage, attempt, None, chars)
            return result
        assert last is not None
        self._record(request, model, False, (self._clock() - started) * 1000, Usage(), attempt, str(last), chars)
        raise last

    def list_models(self) -> list[dict[str, Any]]:
        """``GET /v1/models?verbose=true`` as plain dicts. Needs consent like any other request."""
        authorize(self.config, self.consent)
        try:
            page = self._sdk().models.list(extra_query={"verbose": "true"})
            return [m.model_dump() for m in page]
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def health(self) -> HealthStatus:
        from sketchforge.integrations.nebius.health_check import run_health_check

        return run_health_check(self)

    # ------------------------------------------------------------------ internals
    def _delay(self, attempt: int, err: ProviderError) -> float:
        base = min(self.config.backoff_cap_s, self.config.backoff_base_s * (2 ** (attempt - 1)))
        delay = base * (0.5 + self._jitter() / 2)
        if isinstance(err, ProviderRateLimited) and err.retry_after_s is not None:
            delay = max(delay, min(err.retry_after_s, self.config.backoff_cap_s))
        return delay

    def _parse(
        self,
        response: Any,
        model: str,
        attempt: int,
        latency_ms: float,
        request: CompletionRequest | None = None,
    ) -> CompletionResult:
        choices = getattr(response, "choices", None)
        if not choices:
            raise ProviderBadResponse("the service returned no choices")
        choice = choices[0]
        content = getattr(getattr(choice, "message", None), "content", None)
        finish = getattr(choice, "finish_reason", None)
        if not isinstance(content, str) or not content.strip():
            raise ProviderBadResponse("the service returned an empty answer")
        if finish == "length":
            if request is not None and getattr(request, "purpose", None) in ("studio_file", "studio_ping"):
                log.warning(
                    "nebius: finish_reason=length for model=%s (request may be truncated); "
                    "returning partial content for caller to handle.",
                    model,
                )
            else:
                raise ProviderBadResponse("the answer was cut off (max_tokens reached); it would not be valid JSON")
        usage = getattr(response, "usage", None)
        return CompletionResult(
            text=content, model=str(getattr(response, "model", None) or model),
            usage=Usage(int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)),
            latency_ms=latency_ms, attempts=attempt, finish_reason=finish,
            request_id=getattr(response, "id", None))

    def _record(self, request: CompletionRequest, model: str, ok: bool, latency_ms: float, usage: Usage,
                attempts: int, error: str | None, chars: int) -> None:
        self._usage.append(UsageRecord(self.name, model, request.purpose, ok, round(latency_ms, 1),
                                       usage.prompt_tokens, usage.completion_tokens, attempts, error, chars))
