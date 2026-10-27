"""Lint runner: runs ESLint (JS/TS) and ruff (Python) inside the sandbox."""
from __future__ import annotations

import time
from pathlib import Path

from sketchforge.execution.sandbox import SandboxSession
from sketchforge.verification.verification_report import VerificationStep


def run_lint(session: SandboxSession, project_root: Path) -> VerificationStep:
    """Run ESLint on the generated TypeScript/React source."""
    t0 = time.perf_counter()
    # Check if ESLint is available (via npx after npm install)
    r = session.run(
        ["npx", "eslint", "src", "--ext", ".ts,.tsx", "--max-warnings", "10"],
        cwd=project_root,
        timeout=60,
    )
    return VerificationStep(
        name="eslint",
        ok=r.ok,
        duration_ms=(time.perf_counter() - t0) * 1000,
        stdout=r.stdout,
        stderr=r.stderr,
        returncode=r.returncode,
    )


def run_typecheck(session: SandboxSession, project_root: Path) -> VerificationStep:
    """Run tsc --noEmit inside the sandbox."""
    t0 = time.perf_counter()
    r = session.run(
        ["npx", "tsc", "--noEmit"],
        cwd=project_root,
        timeout=60,
    )
    return VerificationStep(
        name="tsc --noEmit",
        ok=r.ok,
        duration_ms=(time.perf_counter() - t0) * 1000,
        stdout=r.stdout,
        stderr=r.stderr,
        returncode=r.returncode,
    )
