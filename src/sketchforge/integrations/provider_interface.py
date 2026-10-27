"""The provider contract: what the application needs from any model provider.

Application code (``assist/``) builds a :class:`CompletionRequest`, calls
:meth:`ModelProvider.complete`, and gets a :class:`CompletionResult` back. It never sees a
provider's wire format, SDK objects or error classes: those are translated into this module's
types inside ``integrations/<provider>/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from sketchforge.exceptions import SketchForgeError


class ProviderError(SketchForgeError):
    """Base class for every failure a provider can report."""

    retryable: bool = False


class ProviderDisabled(ProviderError):
    """Remote use is switched off or the user has not consented."""


class ProviderAuthError(ProviderError):
    """Missing, invalid or unauthorised credentials."""


class ProviderRateLimited(ProviderError):
    retryable = True

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    """Network failure or a 5xx from the service."""

    retryable = True


class ProviderBadResponse(ProviderError):
    """The service answered, but not with something usable (empty, truncated, not JSON, ...)."""


class PolicyViolation(ProviderError):
    """A request was refused locally before anything was sent (size, image, text policy)."""


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    messages: tuple[ChatMessage, ...]
    purpose: str  # short label recorded in the usage log, e.g. "nl_edit"
    max_tokens: int = 700
    temperature: float = 0.0
    json_mode: bool = False
    model: str | None = None  # None = the provider's configured default


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model: str
    usage: Usage
    latency_ms: float
    attempts: int = 1
    finish_reason: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    provider: str
    detail: str
    model: str | None = None
    model_available: bool | None = None
    latency_ms: float | None = None
    models_seen: tuple[str, ...] = ()
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass
class UsageRecord:
    """One line of the local usage log (no prompt or response content is stored)."""

    provider: str
    model: str
    purpose: str
    ok: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 1
    error: str | None = None
    prompt_chars: int = 0


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def health(self) -> HealthStatus: ...

    @property
    def usage_log(self) -> list[UsageRecord]: ...
