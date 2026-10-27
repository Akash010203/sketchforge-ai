"""Process runner: higher-level orchestration over sandbox.run().

Runs multi-step sequences (install → build → test) and collects structured results.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sketchforge.execution.sandbox import SandboxSession, RunResult


@dataclass
class StepResult:
    name: str
    run: RunResult
    notes: str = ""

    @property
    def ok(self) -> bool:
        return self.run.ok


@dataclass
class ProcessReport:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    @property
    def first_failure(self) -> StepResult | None:
        return next((s for s in self.steps if not s.ok), None)

    def summary(self) -> str:
        lines = []
        for s in self.steps:
            icon = "✓" if s.ok else "✗"
            lines.append(f"  {icon} {s.name}: {s.run.summary()}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "steps": [
                {
                    "name": s.name,
                    "ok": s.ok,
                    "returncode": s.run.returncode,
                    "duration_ms": round(s.run.duration_ms, 1),
                    "stdout": s.run.stdout[-2000:],
                    "stderr": s.run.stderr[-2000:],
                    "timed_out": s.run.timed_out,
                    "notes": s.notes,
                }
                for s in self.steps
            ],
        }


def npm_workflow(session: SandboxSession, project_root: Path) -> ProcessReport:
    """Run npm install → tsc typecheck → npm run build → npm test on a React project."""
    report = ProcessReport()

    # 1. npm install
    r = session.run(["npm", "install", "--legacy-peer-deps"], cwd=project_root, timeout=180)
    report.steps.append(StepResult("npm install", r))
    if not r.ok:
        return report  # stop: nothing can work without dependencies

    # 2. TypeScript type check
    r = session.run(["npx", "tsc", "--noEmit"], cwd=project_root, timeout=60)
    report.steps.append(StepResult("tsc --noEmit", r))

    # 3. Build
    r = session.run(["npm", "run", "build"], cwd=project_root, timeout=120)
    report.steps.append(StepResult("npm run build", r))

    return report


def pytest_workflow(session: SandboxSession, project_root: Path) -> ProcessReport:
    """Run pytest on a generated Python backend."""
    report = ProcessReport()
    r = session.run(
        ["python", "-m", "pytest", "backend/tests", "-v", "--tb=short"],
        cwd=project_root,
        timeout=60,
    )
    report.steps.append(StepResult("pytest backend", r))
    return report
