"""Command line entry point: ``python -m sketchforge <command>`` (or ``sketchforge <command>``).

    demo        run the full sketch -> design -> measure -> inject -> repair -> report workflow headless
    gui         open the desktop workbench
    studio      run the local browser-based app generator studio
    info        print the environment and versions
    cloud       offload sketch processing to the SketchForge AWS Lambda endpoint (--cloud-aws)

Pass ``--cloud-aws`` to the ``demo`` command or use the standalone ``cloud`` subcommand to
forward a sketch image to the deployed AWS API Gateway endpoint and receive the Design IR.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sketchforge import __version__
from sketchforge.repair.error_injection import KINDS
from sketchforge.utilities.paths import repo_root

DEFAULT_SAMPLE = "login_page_synthetic.png"


def _default_image() -> Path:
    return repo_root() / "assets" / "sample_sketches" / DEFAULT_SAMPLE


def cmd_demo(args: argparse.Namespace) -> int:
    from sketchforge.orchestration.sketch_workflow import DEMO_STEPS, run_sketch_workflow
    from sketchforge.orchestration.workflow_state import RunStatus

    image = Path(args.image) if args.image else _default_image()
    if not image.is_file():
        print(f"error: sketch not found: {image}", file=sys.stderr)
        return 2
    out = Path(args.out)
    steps = [s for s in DEMO_STEPS if args.inject != "none" or s != "inject"]
    print(f"SketchForge {__version__}: {image.name} -> {out}")

    def on_progress(step: str, index: int, total: int) -> None:
        print(f"  [{index + 1}/{len(steps)}] {step} ...", flush=True)

    state = run_sketch_workflow(
        image, steps=steps, inject_kind=None if args.inject == "none" else args.inject,
        repair=not args.no_repair, output_dir=out, name=image.stem, on_progress=on_progress)
    print()
    for rec in state.history.to_list():
        print(f"  {rec['status']:8s} {rec['step']:13s} {rec['duration_ms']:8.0f} ms  {rec['detail']}")
    if state.status is not RunStatus.SUCCEEDED:
        print(f"\nFAILED at '{state.failed_step}': {state.error}", file=sys.stderr)
        return 1
    report = state.context.get("report")
    print()
    if report is not None:
        print("RESULT:", report.headline())
        print(f"       stop reason: {report.stop_reason}")
    print(f"Outputs in {out}/  (open reports/repair_report.md and renders/ first)")
    # success = nothing left to fix, or measurably better; REGRESSED / UNABLE_TO_VERIFY fail the demo
    ok = report is None or not report.final.issues or report.outcome.value == "IMPROVED"
    return 0 if ok and not (report and report.outcome.value == "REGRESSED") else 3


def cmd_gui(args: argparse.Namespace) -> int:
    from sketchforge.app import run_gui

    return run_gui(Path(args.image) if args.image else None,
                   screenshot=Path(args.screenshot) if args.screenshot else None)


def cmd_studio(args: argparse.Namespace) -> int:
    from sketchforge.ui.web_studio import serve_studio
    serve_studio(host=args.host, port=args.port)
    return 0


def cmd_info(_: argparse.Namespace) -> int:
    import platform

    import cv2
    import numpy

    print(f"sketchforge {__version__}\npython     {platform.python_version()}  ({platform.platform()})")
    print(f"opencv     {cv2.__version__}\nnumpy      {numpy.__version__}")
    try:
        import PySide6

        print(f"pyside6    {PySide6.__version__}")
    except ImportError:
        print("pyside6    not installed (the GUI is unavailable; the CLI works)")
    print(f"samples    {sorted(p.name for p in (repo_root() / 'assets' / 'sample_sketches').glob('*.png'))}")
    return 0


def cmd_cloud(args: argparse.Namespace) -> int:
    """Offload sketch processing to the SketchForge AWS Lambda endpoint.

    Reads ``--image``, sends it to the competition Lambda endpoint, and writes the
    returned Design IR to ``--out``.
    """
    import json as _json

    from sketchforge.cloud.aws_client import AWSClientError, AWSSketchClient

    image = Path(args.image) if args.image else _default_image()
    if not image.is_file():
        print(f"error: sketch not found: {image}", file=sys.stderr)
        return 2

    endpoint = args.endpoint or None  # None triggers env-var / CFN auto-discovery
    try:
        client = AWSSketchClient(endpoint=endpoint)
    except AWSClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"SketchForge cloud (AWS Lambda): {image.name}")
    print(f"  endpoint : {client._endpoint}")
    print("  health   : ", end="", flush=True)
    ok = client.health_check()
    print("ok" if ok else "UNREACHABLE (proceeding anyway)")

    try:
        result = client.process_image_file(image)
    except AWSClientError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ir_path = out / f"{image.stem}_design_ir.json"
    ir_path.write_text(
        _json.dumps(result.design_document.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n  round-trip : {result.latency_ms:.0f} ms")
    print(f"  pipeline   : {result.pipeline_version}")
    print(f"  components : {len(result.design_document.components)}")
    if result.notes:
        print("  notes:")
        enc = sys.stdout.encoding or "utf-8"
        for note in result.notes:
            safe_note = note.encode(enc, errors="replace").decode(enc)
            print(f"    * {safe_note}")
    print(f"\nDesign IR saved to {ir_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sketchforge", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"sketchforge {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="headless end-to-end demo with a measured repair")
    d.add_argument("--image", help=f"sketch to import (default: assets/sample_sketches/{DEFAULT_SAMPLE})")
    d.add_argument("--inject", default="overflow", choices=[*KINDS, "none"],
                   help="layout fault to inject before repairing (default: overflow; 'none' repairs what "
                        "the evaluator finds on the imported design)")
    d.add_argument("--no-repair", action="store_true", help="measure only; do not run the repair loop")
    d.add_argument("--out", default="output/demo", help="output directory (default: output/demo)")
    d.set_defaults(func=cmd_demo)

    g = sub.add_parser("gui", help="open the desktop workbench")
    g.add_argument("--image", help="sketch to import on start")
    g.add_argument("--screenshot", help="headless: import, inject a fault, save a PNG of the window, exit")
    g.set_defaults(func=cmd_gui)

    w = sub.add_parser("studio", help="run the local browser-based app generator studio")
    w.add_argument("--host", default="127.0.0.1", help="bind locally by default")
    w.add_argument("--port", type=int, default=8000)
    w.set_defaults(func=cmd_studio)

    i = sub.add_parser("info", help="print versions and bundled samples")
    i.set_defaults(func=cmd_info)

    # ------------------------------------------------------------------
    # cloud (--cloud-aws flag)
    # ------------------------------------------------------------------
    cl = sub.add_parser(
        "cloud",
        help="offload sketch processing to the AWS Lambda endpoint (--cloud-aws)",
        description=(
            "Send a sketch photo to the SketchForge AWS Lambda endpoint and receive the "
            "Design IR JSON.  Activate with: sketchforge cloud --image sketch.jpg "
            "--endpoint https://<api-id>.execute-api.<region>.amazonaws.com/production"
        ),
    )
    cl.add_argument("--image", help="sketch photo to process (default: built-in sample)")
    cl.add_argument(
        "--endpoint",
        metavar="URL",
        help=(
            "AWS API Gateway base URL. Overrides the SKETCHFORGE_AWS_ENDPOINT env var. "
            "If omitted, auto-discovered from the SKETCHFORGE_AWS_STACK_NAME CloudFormation stack."
        ),
    )
    cl.add_argument("--out", default="output/cloud", help="output directory (default: output/cloud)")
    # Canonical alias: --cloud-aws mirrors the competition spec language.
    cl.add_argument(
        "--cloud-aws",
        action="store_true",
        default=True,
        help="(default: True) Use AWS Lambda for processing. Alias kept for competition spec compatibility.",
    )
    cl.set_defaults(func=cmd_cloud)

    return p


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if "--cloud-aws" in args_list and not any(
        cmd in args_list for cmd in ["demo", "gui", "studio", "info", "cloud"]
    ):
        args_list.insert(0, "cloud")
    args = build_parser().parse_args(args_list)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
