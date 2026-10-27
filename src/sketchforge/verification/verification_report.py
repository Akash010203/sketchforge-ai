"""Verification report: structured results from the verification pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VerificationStep:
    name: str
    ok: bool
    duration_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    notes: str = ""


@dataclass
class VerificationReport:
    project_root: str
    steps: list[VerificationStep] = field(default_factory=list)
    screenshot_path: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.ok)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if not s.ok)

    def add(self, step: VerificationStep) -> None:
        self.steps.append(step)

    def summary(self) -> str:
        lines = [f"Verification: {'PASS' if self.ok else 'FAIL'} ({self.passed}/{len(self.steps)} steps)"]
        for s in self.steps:
            icon = "✓" if s.ok else "✗"
            lines.append(f"  {icon} {s.name} ({s.duration_ms:.0f} ms)")
            if not s.ok and s.stderr:
                for line in s.stderr.strip().splitlines()[:5]:
                    lines.append(f"      {line}")
        if self.screenshot_path:
            lines.append(f"  📷 Screenshot: {self.screenshot_path}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "passed": self.passed,
            "failed": self.failed,
            "project_root": self.project_root,
            "screenshot": self.screenshot_path,
            "steps": [
                {
                    "name": s.name,
                    "ok": s.ok,
                    "duration_ms": round(s.duration_ms, 1),
                    "returncode": s.returncode,
                    "stdout": s.stdout[-1000:],
                    "stderr": s.stderr[-1000:],
                    "notes": s.notes,
                }
                for s in self.steps
            ],
            "notes": self.notes,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
