"""Build runner: executes npm run build inside the sandbox."""
from __future__ import annotations

import time
from pathlib import Path

from sketchforge.execution.sandbox import SandboxSession
from sketchforge.verification.verification_report import VerificationStep


def run_build(session: SandboxSession, project_root: Path) -> VerificationStep:
    """Execute the Vite production build."""
    t0 = time.perf_counter()
    r = session.run(["npm", "run", "build"], cwd=project_root, timeout=120)
    dist = project_root / "dist"
    notes = ""
    if r.ok and dist.is_dir():
        files = list(dist.rglob("*"))
        notes = f"dist/ has {len(files)} output files"
    elif r.ok:
        notes = "build succeeded (dist/ not found — may be configured differently)"
    return VerificationStep(
        name="npm run build",
        ok=r.ok,
        duration_ms=(time.perf_counter() - t0) * 1000,
        stdout=r.stdout,
        stderr=r.stderr,
        returncode=r.returncode,
        notes=notes,
    )
