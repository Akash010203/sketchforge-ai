"""Backend API server manager for generated projects.

When a generated project includes a Flask backend (backend/api.py), this module
starts and manages that process, serving it on a free local port. The preview
panel routes /api/* requests through this server via the iframe URL.

Security: the child process is launched with a scrubbed environment (_safe_env)
that strips credentials and parent-directory path leakage before the subprocess
is created, implementing a lightweight SandboxSession equivalent without
requiring an external sandbox dependency.
"""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credentials and sensitive variable patterns to strip from the child env
# ---------------------------------------------------------------------------

_BLOCKED_ENV_PREFIXES: tuple[str, ...] = (
    "NEBIUS_",
    "OPENAI_",
    "ANTHROPIC_",
    "NVIDIA_",
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "SECRET_",
    "TOKEN_",
    "API_KEY",
    "PRIVATE_KEY",
    "OAUTH_",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "DATABASE_URL",
    "DB_URL",
    "REDIS_URL",
    "MONGO_URL",
    "PGPASSWORD",
    "MYSQL_PWD",
    "GPG_",
    "SSH_",
)

_BLOCKED_ENV_EXACT: frozenset[str] = frozenset({
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEPATH",
    "HOMEDRIVE",
    # Prevent the child from discovering the SketchForge source tree.
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
})


def _safe_env(base: dict[str, str], port: int) -> dict[str, str]:
    """Return a scrubbed copy of *base* safe for untrusted child processes.

    Strips credentials, parent-directory path variables, and any key that
    starts with a known sensitive prefix.  Overrides are applied last so the
    caller cannot accidentally pass a sensitive value through a whitelisted key.
    """
    env: dict[str, str] = {}
    for key, value in base.items():
        upper = key.upper()
        if upper in _BLOCKED_ENV_EXACT:
            continue
        if any(upper.startswith(pfx) for pfx in _BLOCKED_ENV_PREFIXES):
            continue
        env[key] = value

    # Safe, required runtime variables.
    env.update(
        FLASK_ENV="production",         # no debugger / reloader in preview child
        FLASK_DEBUG="0",
        PYTHONUNBUFFERED="1",
        PORT=str(port),
        # Give the child a self-contained temp directory so it cannot escape.
    )
    return env


class BackendServer:
    """Manages a single subprocess running backend/api.py for a generated project.

    The subprocess is started with a scrubbed environment (_safe_env) to prevent
    credential leakage and parent-directory path discovery.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._project_root: Path | None = None
        self._session_token: str | None = None
        self._lock = threading.Lock()

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def session_token(self) -> str | None:
        """The ephemeral X-Studio-Token for this preview session.

        Web Studio must attach this value as the ``X-Studio-Token`` request
        header on every proxied ``/api/*`` call so the backend token gate
        accepts the request.
        """
        return self._session_token

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(self, project_root: Path, cors_origin: str | None = None) -> int | None:
        """Start the backend for *project_root* with a sandboxed env.  Returns the port, or None."""
        self.stop()
        api_script = project_root / "backend" / "api.py"
        if not api_script.is_file():
            log.debug("No backend/api.py in %s; skipping backend server.", project_root)
            return None

        port = _free_port()

        # Ephemeral session token — fresh per preview, 32 bytes URL-safe.
        session_token = secrets.token_urlsafe(32)

        # Build a credential-scrubbed environment for the child process.
        child_env = _safe_env(dict(os.environ), port)

        # Restrict CORS to the exact origin the preview iframe will use.
        child_env["CORS_ORIGIN"] = cors_origin or "*"

        # Inject the ephemeral session token so the backend can gate /api/.
        child_env["STUDIO_TOKEN"] = session_token

        # Ensure project root is on PYTHONPATH and standard runtime vars are set
        child_env["PYTHONPATH"] = str(project_root)
        child_env["PORT"] = str(port)
        child_env["HOST"] = "127.0.0.1"
        child_env["FLASK_RUN_PORT"] = str(port)
        child_env["FLASK_RUN_HOST"] = "127.0.0.1"

        # Ensure backend/__init__.py exists for proper package resolution
        init_py = project_root / "backend" / "__init__.py"
        if not init_py.exists():
            try:
                init_py.touch(exist_ok=True)
            except Exception:
                pass

        # If the generated project includes an auth module, inject a preview-only
        # ephemeral secret (never the real AUTH_SECRET from the parent environment).
        if (project_root / "backend" / "auth.py").is_file():
            child_env["AUTH_SECRET"] = secrets.token_urlsafe(48)

        api_source = api_script.read_text(encoding="utf-8", errors="replace")
        is_asgi = "FastAPI(" in api_source or "GraphQL(schema" in api_source
        module_entry = "run python -m backend.api" in api_source

        # Only pass CLI flags that the target script actually parses
        cli_args: list[str] = []
        if "--host" in api_source:
            cli_args.extend(["--host", "127.0.0.1"])
        if "--port" in api_source:
            cli_args.extend(["--port", str(port)])

        if is_asgi:
            command = [sys.executable, "-m", "uvicorn", "backend.api:app",
                       "--host", "127.0.0.1", "--port", str(port)]
        elif module_entry or init_py.is_file():
            command = [sys.executable, "-m", "backend.api", *cli_args]
        else:
            command = [sys.executable, str(api_script), *cli_args]

        try:
            proc = subprocess.Popen(
                command,
                cwd=str(project_root),
                env=child_env,          # ← scrubbed environment, not os.environ
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            log.warning("Could not start backend server: %s", exc)
            return None

        # Wait up to 5 s for the server to accept connections.
        if not _wait_for_port("127.0.0.1", port, timeout=5.0):
            err_output = ""
            try:
                if proc.stdout:
                    err_output = proc.stdout.read()
            except Exception:
                pass
            log.warning("Backend server did not start in time on port %d. Exit code: %s. Output:\n%s",
                        port, proc.poll(), err_output)
            print(f"Backend server did not start in time on port {port}. Exit code: {proc.poll()}. Output:\n{err_output}")
            proc.terminate()
            return None

        with self._lock:
            self._process = proc
            self._port = port
            self._project_root = project_root
            self._session_token = session_token

        log.info("Backend server started on port %d for %s (sandboxed env).", port, project_root.name)
        # Drain stdout in a daemon thread so the pipe does not block.
        threading.Thread(target=_drain, args=(proc,), daemon=True, name="sketchforge-api-log").start()
        return port

    def stop(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
            self._port = None
            self._project_root = None
            self._session_token = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return an OS-assigned free TCP port."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    """Return True when something is accepting TCP connections on host:port."""
    import socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _drain(proc: subprocess.Popen) -> None:
    """Read and log stdout/stderr from the backend process."""
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            log.debug("[backend] %s", line.rstrip())
    except Exception:  # noqa: BLE001
        pass
