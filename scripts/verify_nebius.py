#!/usr/bin/env python
"""Explicitly verify Nebius Token Factory access and NVIDIA model availability.

No sketch or design data is sent. The only completion is a fixed one-word connectivity probe.
The endpoint does not expose an account's retention setting, so ZDR is reported as unknown.

Usage: set NEBIUS_API_KEY, then run:
       python scripts/verify_nebius.py --enable --accept-egress
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sketchforge.integrations.nebius import (  # noqa: E402
    ConsentGate,
    NebiusClient,
    load_nebius_config,
)
from sketchforge.integrations.nebius.model_registry import nvidia_models, parse_models  # noqa: E402
from sketchforge.integrations.provider_interface import (  # noqa: E402
    ChatMessage,
    CompletionRequest,
    ProviderAuthError,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
)

PREFERRED = ("nvidia/Nemotron-3_5-Lightning", "nvidia/nemotron-3-super-120b-a12b")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--accept-egress", action="store_true",
                        help="acknowledge the displayed Nebius egress notice for this invocation")
    parser.add_argument("--enable", action="store_true",
                        help="enable the provider for this verification run without editing config/providers.yaml")
    parser.add_argument("--model", help="override the configured model for the completion probe")
    parser.add_argument("--out", default="experiments/results/live_nebius_benchmark.json",
                        help="write the verification report here (default: %(default)s)")
    args = parser.parse_args()
    overrides = {"enabled": True} if args.enable else {}
    config = load_nebius_config(overrides=overrides)
    print(
        "Nebius live verification probe: this command requests the model list and sends only the "
        f"fixed prompt 'Reply with the single word: ok' to {config.base_url}. It sends no sketch, "
        "design summary, user instruction, or component text. Nebius may retain inputs and outputs "
        "unless ZDR is enabled for the organisation; the API does not report that setting."
    )
    if not args.accept_egress:
        print("\nNo request sent. Review the notice, then rerun with --accept-egress to proceed.", file=sys.stderr)
        return 2
    if not config.enabled:
        print("\nNo request sent: set nebius.enabled: true in config/providers.yaml or pass --enable.", file=sys.stderr)
        return 2

    consent = ConsentGate()
    consent.acknowledge()
    client = NebiusClient(config, consent)
    report: dict = {
        "provider": "nebius",
        "status": "running",
        "stage": "models_endpoint",
        "endpoint": config.base_url,
        "zdr": {"status": "unknown", "reason": "The inference API does not expose the organization retention setting."},
        "privacy_policy": {
            "allow_images": config.privacy.allow_images,
            "include_user_text": config.privacy.include_user_text,
            "probe_contains_design_data": False,
        },
    }
    try:
        # Check credentials before making any request, and never serialize the secret.
        config.api_key()
        raw = client.list_models()
        models = parse_models(raw)
        ids = {model.model_id for model in models}
        available = [model_id for model_id in PREFERRED if model_id in ids]
        chosen = args.model or (available[0] if available else config.default_model)
        report["models_endpoint"] = {
            "ok": True,
            "count": len(models),
            "nvidia_models": [m.model_id for m in nvidia_models(models)],
            "nvidia_model_details": [
                {"id": m.model_id, "modality": m.modality, "accepts_images": m.accepts_images,
                 "context_length": m.context_length}
                for m in nvidia_models(models)
            ],
            "preferred_available": available,
        }
        report["selected_model"] = chosen
        if chosen not in ids or not chosen.lower().startswith("nvidia/"):
            report["ok"] = False
            report["status"] = "model_unavailable" if chosen not in ids else "not_nvidia_model"
            report["error"] = (
                "selected model is not listed by the live models endpoint; completion probe skipped"
                if chosen not in ids else
                "selected model is not an NVIDIA model; completion probe skipped"
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            print(f"wrote {out}")
            return 1
        report["stage"] = "completion"
        result = client.complete(CompletionRequest(
            messages=(ChatMessage("user", "Reply with the single word: ok"),),
            purpose="verify_nebius", max_tokens=256, model=chosen,
        ))
        report["completion"] = {"ok": bool(result.text.strip()), "model": result.model,
                                 "latency_ms": round(result.latency_ms, 1),
                                 "prompt_tokens": result.usage.prompt_tokens,
                                 "completion_tokens": result.usage.completion_tokens}
        report["model_verified"] = chosen in ids and chosen.startswith("nvidia/")
        report["ok"] = report["completion"]["ok"] and report["model_verified"]
        report["status"] = "verified" if report["ok"] else "verification_failed"
        report["stage"] = "complete"
    except ProviderError as exc:
        report["ok"] = False
        report["error"] = str(exc)
        if isinstance(exc, ProviderAuthError):
            report["status"] = "blocked"
        elif isinstance(exc, ProviderUnavailable):
            report["status"] = "network_error"
        elif isinstance(exc, ProviderTimeout):
            report["status"] = "timeout"
        else:
            report["status"] = "verification_failed"
        report["failed_stage"] = report.pop("stage")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"wrote {out}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
