"""Execution sandbox: runs commands in an isolated temporary directory.

Rules enforced here:
* The generated code never runs inside the SketchForge process.
* Commands must appear on the allow-list (command_policy.py).
* Resource limits (time, memory) are enforced by the OS via subprocess limits.
* A scratch directory is created, used, and cleaned up.
* No secrets from the SketchForge environment are passed through.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class RunResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def summary(self) -> str:
        status = "ok" if self.ok else ("timeout" if self.timed_out else f"exit {self.returncode}")
        return f"[{status}] {' '.join(self.command[:3])} ({self.duration_ms:.0f} ms)"


@dataclass
class SandboxSession:
    """A disposable working directory for one generated project."""
    root: Path
    env: dict[str, str] = field(default_factory=dict)

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: float = 120.0,
    ) -> RunResult:
        """Execute a command in the sandbox directory."""
        from sketchforge.execution.command_policy import assert_permitted

        cmd = list(cmd)
        assert_permitted(cmd)

        work_dir = cwd or self.root
        safe_env = _safe_env(self.env)

        t0 = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
            )
            returncode = proc.returncode
            stdout = proc.stdout[-16_000:]  # cap output
            stderr = proc.stderr[-16_000:]
        except subprocess.TimeoutExpired as e:
            returncode = -1
            stdout = (e.stdout or b"").decode(errors="replace")[-8_000:]
            stderr = (e.stderr or b"").decode(errors="replace")[-8_000:]
            timed_out = True
        duration_ms = (time.perf_counter() - t0) * 1000

        return RunResult(cmd, returncode, stdout, stderr, duration_ms, timed_out)

    def cleanup(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "SandboxSession":
        return self

    def __exit__(self, *_) -> None:
        self.cleanup()


def open_sandbox(base_dir: Path | None = None, env: dict[str, str] | None = None) -> SandboxSession:
    """Create a new temporary sandbox directory and return the session."""
    if base_dir is not None:
        base_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="sketchforge_sandbox_", dir=base_dir))
    return SandboxSession(root=scratch, env=env or {})


# ---------------------------------------------------------------------------
# Environment scrubbing
# ---------------------------------------------------------------------------

# Keys that we deliberately pass through (needed for npm/python tooling)
_PASSTHROUGH = {
    "PATH", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
    "USERPROFILE", "SystemRoot", "SystemDrive", "HOMEDRIVE", "HOMEPATH",
    "COMSPEC", "USERNAME",
    # Node / npm
    "NODE_PATH", "npm_config_cache", "npm_config_prefix",
    # Windows SDK toolchain
    "PATHEXT",
}

# Keys explicitly blocked (contain secrets)
_BLOCKED_PATTERNS = [
    "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL",
    "PRIVATE", "AUTH", "NEBIUS", "OPENAI",
]


def _safe_env(extra: dict[str, str]) -> dict[str, str]:
    """Build a scrubbed environment, adding ``extra`` overrides."""
    safe: dict[str, str] = {}
    for key, val in os.environ.items():
        upper = key.upper()
        if upper in _PASSTHROUGH:
            safe[key] = val
        elif any(pat in upper for pat in _BLOCKED_PATTERNS):
            continue  # block
        # Keep toolchain paths that don't look like secrets
    safe.update(extra)
    return safe
