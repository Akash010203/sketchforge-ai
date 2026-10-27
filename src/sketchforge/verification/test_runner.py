"""Test runner: executes vitest (React) or pytest (Python backend) inside the sandbox."""
from __future__ import annotations

import time
from pathlib import Path

from sketchforge.execution.sandbox import SandboxSession
from sketchforge.verification.verification_report import VerificationStep


def run_tests(session: SandboxSession, project_root: Path) -> VerificationStep:
    """Run available tests: vitest for React, pytest for Python backend."""
    pkg_json = project_root / "package.json"
    if pkg_json.exists():
        return _run_vitest(session, project_root)
    backend = project_root / "backend" / "tests"
    if backend.exists():
        return _run_pytest(session, project_root)
    return VerificationStep(
        name="tests",
        ok=True,
        notes="No test runner found (no package.json or backend/tests/)",
    )


def _run_vitest(session: SandboxSession, root: Path) -> VerificationStep:
    t0 = time.perf_counter()
    r = session.run(
        ["npx", "vitest", "run", "--reporter=verbose"],
        cwd=root,
        timeout=120,
    )
    return VerificationStep(
        name="vitest",
        ok=r.ok,
        duration_ms=(time.perf_counter() - t0) * 1000,
        stdout=r.stdout,
        stderr=r.stderr,
        returncode=r.returncode,
    )


def _run_pytest(session: SandboxSession, root: Path) -> VerificationStep:
    t0 = time.perf_counter()
    r = session.run(
        ["python", "-m", "pytest", "backend/tests", "-v", "--tb=short"],
        cwd=root,
        timeout=60,
    )
    return VerificationStep(
        name="pytest",
        ok=r.ok,
        duration_ms=(time.perf_counter() - t0) * 1000,
        stdout=r.stdout,
        stderr=r.stderr,
        returncode=r.returncode,
    )
