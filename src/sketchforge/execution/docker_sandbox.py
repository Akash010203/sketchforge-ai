"""Docker / gVisor micro-sandbox execution layer.

When Docker is available on the host, generated code runs inside a disposable
container rather than the host Python process.  The container:
  * Uses the ``sketchforge-runner`` image (Node + Python toolchain, no root).
  * Mounts the project directory as a read-write volume at ``/workspace``.
  * Runs with ``--network=none`` (no outbound network).
  * Is limited to 512 MB RAM and 512 CPU shares via Docker resource flags.
  * Is auto-removed when the command finishes (``--rm``).
  * Uses gVisor (runsc) when the host runtime supports it.

Falls back transparently to the existing SandboxSession subprocess runner
when Docker is not installed, preserving the hackathon fast-path.

Usage::

    from sketchforge.execution.docker_sandbox import open_docker_sandbox

    with open_docker_sandbox(project_root) as session:
        result = session.run(["npm", "install"])
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from sketchforge.execution.sandbox import RunResult, SandboxSession, open_sandbox

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants (override via environment variables)
# ---------------------------------------------------------------------------

#: Docker image providing the Node + Python toolchain.
RUNNER_IMAGE: str = os.environ.get("SKETCHFORGE_RUNNER_IMAGE", "sketchforge/runner:latest")

#: gVisor runtime name registered in the Docker daemon.
GVISOR_RUNTIME: str = "runsc"

#: Maximum memory for the container (Docker --memory flag value).
CONTAINER_MEMORY: str = "512m"

#: CPU shares allocated to each container (relative weight, 1024 = 1 CPU).
CONTAINER_CPU_SHARES: str = "512"


# ---------------------------------------------------------------------------
# Docker availability probes
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    """Return True if the docker CLI is on PATH and the daemon responds."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _gvisor_available() -> bool:
    """Return True if the gVisor runtime (runsc) is registered with Docker."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{range $k, $v := .Runtimes}}{{$k}}\n{{end}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return GVISOR_RUNTIME in result.stdout
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Docker sandbox session
# ---------------------------------------------------------------------------

@dataclass
class DockerSandboxSession:
    """Runs commands inside a per-invocation disposable Docker container.

    Each run() call launches a new --rm container which mounts the project
    directory at /workspace.  This avoids a long-lived container that could
    be compromised between steps, and ensures full filesystem reset per step.
    """

    root: Path
    image: str = ""
    use_gvisor: bool = False
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.image:
            self.image = RUNNER_IMAGE

    # ------------------------------------------------------------------
    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: float = 120.0,
    ) -> RunResult:
        """Execute cmd inside the container rooted at /workspace."""
        from sketchforge.execution.command_policy import assert_permitted

        cmd = list(cmd)
        assert_permitted(cmd)

        work_dir = cwd or self.root
        # Translate host path to container path under /workspace
        try:
            rel = work_dir.relative_to(self.root)
            rel_str = rel.as_posix()
            container_cwd = f"/workspace/{rel_str}" if rel_str != "." else "/workspace"
        except ValueError:
            container_cwd = "/workspace"

        docker_cmd = self._build_docker_cmd(cmd, container_cwd)

        t0 = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            returncode = proc.returncode
            stdout = proc.stdout[-16_000:]
            stderr = proc.stderr[-16_000:]
        except subprocess.TimeoutExpired as exc:
            returncode = -1
            stdout = (exc.stdout or b"").decode(errors="replace")[-8_000:]
            stderr = (exc.stderr or b"").decode(errors="replace")[-8_000:]
            timed_out = True
        duration_ms = (time.perf_counter() - t0) * 1000

        return RunResult(cmd, returncode, stdout, stderr, duration_ms, timed_out)

    # ------------------------------------------------------------------
    def _build_docker_cmd(self, cmd: Sequence[str], container_cwd: str) -> list[str]:
        """Construct the full docker run invocation."""
        docker_cmd: list[str] = [
            "docker", "run",
            "--rm",                          # auto-remove after exit
            "--network=none",                # no outbound network access
            "--read-only",                   # read-only root filesystem ...
            "--tmpfs", "/tmp:rw,size=128m",  # ... except /tmp for scratch
            "--memory", CONTAINER_MEMORY,
            "--cpu-shares", CONTAINER_CPU_SHARES,
            "--workdir", container_cwd,
            # Mount only the project directory, not the whole host filesystem.
            "-v", f"{self.root}:/workspace:rw",
        ]

        # Prefer gVisor (runsc) for kernel-level syscall isolation.
        if self.use_gvisor:
            docker_cmd += ["--runtime", GVISOR_RUNTIME]

        # Inject safe environment variables into the container.
        for key, value in self.env.items():
            docker_cmd += ["-e", f"{key}={value}"]

        docker_cmd.append(self.image)
        docker_cmd.extend(cmd)
        return docker_cmd

    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """No persistent container to clean up; root directory is preserved
        so callers can read generated files after the session ends."""

    def __enter__(self) -> "DockerSandboxSession":
        return self

    def __exit__(self, *_) -> None:
        self.cleanup()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def open_docker_sandbox(
    project_root: Path,
    *,
    env: dict[str, str] | None = None,
    image: str | None = None,
    force_subprocess: bool = False,
) -> "DockerSandboxSession | SandboxSession":
    """Return the best available sandbox for project_root.

    Resolution order:
    1. DockerSandboxSession with gVisor runtime (maximum isolation).
    2. DockerSandboxSession with the standard runc runtime.
    3. SandboxSession subprocess fallback (when Docker is unavailable).

    Args:
        project_root: Directory containing the generated project files.
        env: Extra environment variables to inject into the container.
        image: Docker image tag (defaults to RUNNER_IMAGE).
        force_subprocess: Skip Docker even if available (for unit tests).
    """
    chosen_image = image or RUNNER_IMAGE

    if not force_subprocess and _docker_available():
        use_gvisor = _gvisor_available()
        runtime_label = "gVisor+Docker" if use_gvisor else "Docker"
        log.info(
            "Sandbox: using %s container for project %s (image=%s).",
            runtime_label,
            project_root.name,
            chosen_image,
        )
        return DockerSandboxSession(
            root=project_root,
            image=chosen_image,
            use_gvisor=use_gvisor,
            env=env or {},
        )

    log.warning(
        "Docker not available; falling back to subprocess sandbox for project %s.",
        project_root.name,
    )
    # open_sandbox creates a fresh tmpdir; we reuse project_root's parent as base.
    return open_sandbox(base_dir=project_root.parent, env=env or {})


# ---------------------------------------------------------------------------
# Runner Dockerfile (for CI/CD pipeline builds)
# ---------------------------------------------------------------------------

RUNNER_DOCKERFILE: str = """\
# SketchForge sandboxed runner image
# Build: docker build -t sketchforge/runner:latest -f Dockerfile.runner .
FROM node:20-slim AS base

# Minimal Python toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user - generated code MUST NOT run as root
RUN useradd -m -u 1000 runner
USER runner
WORKDIR /workspace

# Expose no ports; network access is denied at the docker run call site.
CMD ["/bin/sh"]
"""


def write_runner_dockerfile(target_dir: Path) -> Path:
    """Write Dockerfile.runner to target_dir for CI/CD pipeline builds."""
    dest = target_dir / "Dockerfile.runner"
    dest.write_text(RUNNER_DOCKERFILE, encoding="utf-8")
    log.info("Wrote runner Dockerfile to %s", dest)
    return dest
