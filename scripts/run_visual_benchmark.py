#!/usr/bin/env python
"""Run the three-arm natural-language edit benchmark.

Three arms are compared:
  local  — Local rule-based parser (no network calls).
  model  — nvidia/Nemotron-3_5-Lightning on Nebius Token Factory.
  hybrid — Nemotron plan with local verification and auto-repair.

Usage
-----
    # Full three-arm run (requires Nebius API key):
    python scripts/run_visual_benchmark.py --accept-egress --enable

    # Local arm only (no network):
    python scripts/run_visual_benchmark.py --arms local

    # Custom output path:
    python scripts/run_visual_benchmark.py --accept-egress --enable \\
        --out experiments/results/three_arm_benchmark.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sketchforge.assist.edit_benchmark import load_tasks, run_benchmark  # noqa: E402
from sketchforge.integrations.nebius import ConsentGate, NebiusClient, egress_notice, load_nebius_config  # noqa: E402
from sketchforge.integrations.provider_interface import ProviderAuthError  # noqa: E402

# Default output targets the canonical three-arm result path committed to the repo.
_DEFAULT_OUT = "experiments/results/three_arm_benchmark.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tasks",
        default="tests/evaluation/edit_tasks.json",
        help="Path to the edit tasks JSON file.",
    )
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=("oracle", "local", "model", "hybrid"),
        default=("local", "model", "hybrid"),
        help=(
            "Arms to include.  'local' is the rule-based baseline, 'model' uses "
            "nvidia/Nemotron-3_5-Lightning on Nebius Token Factory, 'hybrid' adds "
            "local verification and auto-repair on top.  'oracle' is an optional "
            "upper-bound reference control."
        ),
    )
    parser.add_argument(
        "--accept-egress",
        action="store_true",
        help="Acknowledge the Nebius egress notice before running model/hybrid arms.",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable the Nebius provider for this run without editing config/providers.yaml.",
    )
    parser.add_argument(
        "--out",
        default=_DEFAULT_OUT,
        help=f"Output JSON path (default: {_DEFAULT_OUT}).",
    )
    args = parser.parse_args()

    provider = None
    if "model" in args.arms or "hybrid" in args.arms:
        overrides = {"enabled": True} if args.enable else {}
        config = load_nebius_config(overrides=overrides)
        if config.enabled:
            print(egress_notice(config))
            if not args.accept_egress:
                parser.error(
                    "model/hybrid arms send data to Nebius Token Factory. "
                    "Re-run with --accept-egress after reviewing the notice above."
                )
            try:
                config.api_key()
            except ProviderAuthError as exc:
                parser.error(str(exc))
            consent = ConsentGate()
            consent.acknowledge()
            provider = NebiusClient(config, consent)
            print(
                f"  Model: nvidia/Nemotron-3_5-Lightning  "
                f"via {config.base_url or 'Nebius Token Factory'}"
            )
        elif "model" in args.arms:
            parser.error(
                "The model arm requires nebius.enabled: true in config/providers.yaml "
                "or the --enable flag."
            )

    print(f"\nRunning {len(args.arms)} arm(s): {', '.join(args.arms)}")
    result = run_benchmark(load_tasks(args.tasks), arms=tuple(args.arms), provider=provider)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print("\n-- Summary --------------------------------")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))

    # Print delta table
    summary = result.get("summary", {})
    arms_present = list(summary.keys())
    if "local" in arms_present and len(arms_present) > 1:
        print("\n-- Delta vs. local baseline ---------------")
        local_rate = summary["local"].get("pass_rate", 0.0)
        for arm in arms_present:
            if arm == "local":
                continue
            arm_rate = summary[arm].get("pass_rate", 0.0)
            delta = arm_rate - local_rate
            print(f"  {arm:8s}: {arm_rate:.4f}  ({delta:+.4f} vs local)")

    print(f"\nWrote: {out}")
    # Exit 0 — a benchmark run succeeds when all requested tasks are evaluated;
    # arm scores are data, not pass/fail criteria.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
