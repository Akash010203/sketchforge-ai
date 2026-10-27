"""What may leave the machine, and the user's consent to it.

Three layers, all enforced *before* any request is built:
1. configuration must enable the provider (off by default);
2. the user must acknowledge the egress notice for this session (``ConsentGate``);
3. each request is checked against the privacy limits (size; no images unless explicitly allowed).
"""

from __future__ import annotations

import threading
import time

from sketchforge.integrations.nebius.configuration import NebiusConfig
from sketchforge.integrations.provider_interface import (
    CompletionRequest,
    PolicyViolation,
    ProviderDisabled,
)


class ConsentGate:
    """Per-session record that the user has seen and accepted the egress notice."""

    def __init__(self, *, consented: bool = False) -> None:
        self._acknowledged_at: float | None = time.time() if consented else None
        self._lock = threading.Lock()

    @property
    def acknowledged(self) -> bool:
        return self._acknowledged_at is not None

    def acknowledge(self) -> None:
        with self._lock:
            self._acknowledged_at = time.time()

    def revoke(self) -> None:
        with self._lock:
            self._acknowledged_at = None


def egress_notice(config: NebiusConfig) -> str:
    """The text a UI must show before the first request. Plain, specific, no marketing."""
    text_rule = ("the text inside your components IS included" if config.privacy.include_user_text
                 else "the text inside your components is NOT included (only its length)")
    image_rule = ("images MAY be sent" if config.privacy.allow_images else "your sketch image is NOT sent")
    return (
        "Remote assistance is about to send data to Nebius Token Factory "
        f"({config.base_url}) using the model {config.default_model}.\n\n"
        "What is sent: your instruction and a compact structured summary of the current design "
        f"(component ids, types, positions and sizes). {image_rule}; {text_rule}.\n\n"
        "What Nebius does with it (from its Legal Quick Guide): unless Zero Data Retention is enabled "
        "on your Nebius organisation, inputs and outputs are retained (stored in the EU) and may be "
        "used for speculative decoding; content is not used to train models. Processing location on "
        "public endpoints is chosen dynamically.\n\n"
        "Nothing is sent unless you accept. You can revoke at any time; local editing, evaluation and "
        "repair never need the network."
    )


def authorize(config: NebiusConfig, consent: ConsentGate) -> None:
    if not config.enabled:
        raise ProviderDisabled("remote assistance is disabled (config/providers.yaml: nebius.enabled)")
    if not consent.acknowledged:
        raise ProviderDisabled("the user has not acknowledged what will be sent to Nebius in this session")


def check_request(config: NebiusConfig, request: CompletionRequest) -> int:
    """Raise :class:`PolicyViolation` if the request breaks the privacy limits; return its size."""
    chars = sum(len(m.content) for m in request.messages)
    if chars > config.privacy.max_prompt_chars:
        raise PolicyViolation(
            f"prompt is {chars} characters; the limit is {config.privacy.max_prompt_chars} "
            "(nebius.privacy.max_prompt_chars)")
    if not request.messages:
        raise PolicyViolation("a request needs at least one message")
    if request.max_tokens <= 0 or request.max_tokens > 4096:
        raise PolicyViolation("max_tokens must be between 1 and 4096")
    return chars
