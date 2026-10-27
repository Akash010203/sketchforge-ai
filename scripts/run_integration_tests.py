"""Run the full automated test suite and produce a structured report.

Runs pytest over unit, integration, and end-to-end test suites, then
writes a JSON summary to ``experiments/results/test_run_report.json``.

Usage
-----
    python -I scripts/run_integration_tests.py [--unit] [--integration] [--e2e]
                                               [--fast] [--out PATH]

Options
-------
--unit          Run unit tests only
--integration   Run integration tests only
--e2e           Run end-to-end tests only
--fast          Skip slow tests (adds -m "not slow" filter)
--out PATH      JSON report output path
                (default: experiments/results/test_run_report.json)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SUITES = {
    "unit": "tests/unit",
    "integration": "tests/integration",
    "e2e": "tests/end_to_end",
    "generation": "tests/test_generation_pipeline.py",
}


def _run_suite(name: str, path: str, fast: bool) -> dict:
    full_path = ROOT / path
    if not full_path.exists():
        return {"name": name, "skipped": True, "reason": f"path not found: {path}"}

    cmd = [
        sys.executable, "-m", "pytest", str(full_path),
        "-v", "--tb=short", "--no-header",
        "--json-report", "--json-report-file=-",
    ]
    if fast:
        cmd += ["-m", "not slow"]

    t0 = time.perf_counter()
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300
    )
    elapsed = time.perf_counter() - t0

    # Try to parse JSON report from stdout
    passed = failed = errors = warnings = 0
    output = result.stdout + result.stderr

    # Basic parse from pytest summary line
    for line in output.splitlines():
        if " passed" in line or " failed" in line or " error" in line:
            import re
            m = re.findall(r"(\d+) (passed|failed|error|warning)", line)
            for count, kind in m:
                if kind == "passed":
                    passed += int(count)
                elif kind == "failed":
                    failed += int(count)
                elif kind == "error":
                    errors += int(count)
                elif kind == "warning":
                    warnings += int(count)

    return {
        "name": name,
        "path": path,
        "returncode": result.returncode,
        "ok": result.returncode == 0,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
        "stdout_tail": output[-3000:],  # last 3 KB for diagnosis
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unit", action="store_true", help="Run unit tests only")
    ap.add_argument("--integration", action="store_true", help="Run integration tests only")
    ap.add_argument("--e2e", action="store_true", help="Run end-to-end tests only")
    ap.add_argument("--fast", action="store_true", help="Skip tests marked 'slow'")
    ap.add_argument("--out", default="experiments/results/test_run_report.json",
                    help="JSON report output path")
    args = ap.parse_args()

    # Default: run all suites
    run_unit = args.unit or not any([args.unit, args.integration, args.e2e])
    run_integration = args.integration or not any([args.unit, args.integration, args.e2e])
    run_e2e = args.e2e or not any([args.unit, args.integration, args.e2e])

    suites_to_run = []
    if run_unit:
        suites_to_run.append(("unit", "tests/unit"))
        suites_to_run.append(("generation", "tests/test_generation_pipeline.py"))
    if run_integration:
        suites_to_run.append(("integration", "tests/integration"))
    if run_e2e:
        suites_to_run.append(("e2e", "tests/end_to_end"))

    print("=" * 60)
    print("SketchForge Automated Test Suite")
    print("=" * 60)
    print()

    results = []
    all_ok = True

    for name, path in suites_to_run:
        print(f"Running {name} suite ({path}) …")
        r = _run_suite(name, path, args.fast)
        results.append(r)

        if r.get("skipped"):
            print(f"  SKIPPED: {r['reason']}")
        else:
            status = "✓ PASS" if r["ok"] else "✗ FAIL"
            print(f"  {status}  passed={r['passed']}  failed={r['failed']}  "
                  f"errors={r['errors']}  ({r['elapsed_seconds']}s)")
            if not r["ok"]:
                all_ok = False
                # Print last few lines of output for quick diagnosis
                for line in r["stdout_tail"].splitlines()[-20:]:
                    print(f"    {line}")
        print()

    # Summary
    total_passed = sum(r.get("passed", 0) for r in results)
    total_failed = sum(r.get("failed", 0) for r in results)
    total_errors = sum(r.get("errors", 0) for r in results)
    print("=" * 60)
    print(f"TOTAL: passed={total_passed}  failed={total_failed}  errors={total_errors}")
    print("STATUS:", "ALL PASS ✓" if all_ok else "SOME FAILED ✗")
    print()

    # Save report
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": all_ok,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_errors": total_errors,
        "suites": results,
    }
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report saved to {out.relative_to(ROOT)}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
