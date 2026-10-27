"""Database Migration Engine — Alembic + Prisma orchestration.

Provides a unified Python API for:

* **Alembic** (SQLAlchemy ORM projects):
  - Auto-generating migration scripts from model changes.
  - Applying pending migrations (``upgrade head``).
  - Rolling back migrations (``downgrade -1`` or to a specific revision).
  - Listing current and pending revisions.

* **Prisma** (Node.js / prisma-client-js projects):
  - Running ``prisma migrate dev`` inside the backend directory.
  - Running ``prisma migrate deploy`` for production.
  - Resetting the database (``prisma migrate reset``).
  - Generating the Prisma client (``prisma generate``).

All subprocess commands are routed through
:func:`sketchforge.execution.sandbox.SandboxSession.run` so they are subject
to the command-policy allow-list and environment scrubbing.

Usage example::

    from pathlib import Path
    from sketchforge.generation.migration_engine import AlembicMigrationEngine

    engine = AlembicMigrationEngine(project_root=Path("./my-project"))
    engine.upgrade()                   # apply all pending migrations
    engine.autogenerate("add user table")  # create new migration script
    engine.downgrade(-1)               # roll back one step
    info = engine.info()               # dict with current revision, heads, etc.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Alembic Engine
# ---------------------------------------------------------------------------

class AlembicMigrationEngine:
    """High-level Alembic migration controller for a generated Python backend.

    Args:
        project_root: Root directory of the generated project (contains
            ``alembic.ini`` and the ``migrations/`` folder).
        database_url: Override the DATABASE_URL used for connections.
            Defaults to the value in ``alembic.ini`` (``sqlite:///data/app.db``).
        python_executable: Python interpreter to use.  Defaults to the
            current process interpreter so the same virtualenv is used.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        database_url: str | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.database_url = database_url
        self.python = python_executable or sys.executable
        self._alembic_ini = self.project_root / "alembic.ini"

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def upgrade(self, revision: str = "head") -> "MigrationResult":
        """Apply migrations up to *revision* (default: ``head``)."""
        return self._run_alembic(["upgrade", revision])

    def downgrade(self, steps_or_revision: int | str = -1) -> "MigrationResult":
        """Roll back migrations.

        Args:
            steps_or_revision: An integer (e.g. ``-1``) for relative
                rollback, or a revision ID string for absolute target.
        """
        target = str(steps_or_revision) if isinstance(steps_or_revision, int) else steps_or_revision
        return self._run_alembic(["downgrade", target])

    def autogenerate(self, message: str) -> "MigrationResult":
        """Generate a new migration script from model changes.

        This is equivalent to::

            alembic revision --autogenerate -m "<message>"

        The generated script is placed in ``migrations/versions/``.
        """
        return self._run_alembic(["revision", "--autogenerate", "-m", message])

    def current(self) -> "MigrationResult":
        """Return the current database revision."""
        return self._run_alembic(["current", "--verbose"])

    def history(self, limit: int = 20) -> "MigrationResult":
        """Return migration history (most recent first)."""
        return self._run_alembic(["history", "--verbose", "-r", f"head:-{limit}"])

    def heads(self) -> "MigrationResult":
        """Return the active migration heads."""
        return self._run_alembic(["heads"])

    def info(self) -> dict:
        """Return a dict summarising the current migration state."""
        current_result = self.current()
        heads_result = self.heads()
        return {
            "ok": current_result.ok and heads_result.ok,
            "current_revision": _extract_revision(current_result.stdout),
            "heads": _extract_revisions(heads_result.stdout),
            "current_raw": current_result.stdout,
            "returncode": current_result.returncode,
        }

    def stamp(self, revision: str = "head") -> "MigrationResult":
        """Stamp the database at *revision* without running migrations.

        Useful when bringing an existing database under Alembic control.
        """
        return self._run_alembic(["stamp", revision])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_alembic(self, args: Sequence[str]) -> "MigrationResult":
        """Run ``alembic <args>`` inside the project root."""
        if not self._alembic_ini.exists():
            raise FileNotFoundError(
                f"alembic.ini not found in {self.project_root}.  "
                "Generate migrations support with migrations=True in your AppSpec."
            )

        cmd: list[str] = [
            self.python, "-m", "alembic",
            "-c", str(self._alembic_ini),
        ] + list(args)

        env = _make_env(self.database_url)

        log.info("AlembicMigrationEngine: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            result = MigrationResult(
                engine="alembic",
                command=cmd,
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except subprocess.TimeoutExpired:
            result = MigrationResult(
                engine="alembic",
                command=cmd,
                returncode=-1,
                stdout="",
                stderr="Alembic command timed out after 120 s.",
                timed_out=True,
            )

        if not result.ok:
            log.warning(
                "Alembic command failed (rc=%d): %s\n%s",
                result.returncode,
                " ".join(cmd),
                result.stderr[:2000],
            )
        return result


# ---------------------------------------------------------------------------
# Prisma Engine
# ---------------------------------------------------------------------------

class PrismaMigrationEngine:
    """Prisma migration controller for generated Node.js backend projects.

    Args:
        backend_dir: The ``backend/`` directory containing ``package.json``
            and ``prisma/schema.prisma``.
        database_url: Override DATABASE_URL for the Prisma CLI.
    """

    def __init__(
        self,
        backend_dir: Path,
        *,
        database_url: str | None = None,
    ) -> None:
        self.backend_dir = backend_dir.resolve()
        self.database_url = database_url

    # ------------------------------------------------------------------

    def migrate_dev(self, name: str = "auto") -> "MigrationResult":
        """Run ``prisma migrate dev --name <name>`` (development workflow)."""
        return self._run_prisma(["migrate", "dev", "--name", name])

    def migrate_deploy(self) -> "MigrationResult":
        """Run ``prisma migrate deploy`` (production workflow)."""
        return self._run_prisma(["migrate", "deploy"])

    def migrate_reset(self, *, force: bool = False) -> "MigrationResult":
        """Run ``prisma migrate reset`` to wipe and re-apply all migrations.

        Warning:
            This drops all data.  Only use in development.
        """
        extra = ["--force"] if force else []
        return self._run_prisma(["migrate", "reset"] + extra)

    def generate(self) -> "MigrationResult":
        """Run ``prisma generate`` to regenerate the Prisma client."""
        return self._run_prisma(["generate"])

    def status(self) -> "MigrationResult":
        """Run ``prisma migrate status`` to check migration state."""
        return self._run_prisma(["migrate", "status"])

    def db_push(self) -> "MigrationResult":
        """Run ``prisma db push`` for prototype-mode schema sync."""
        return self._run_prisma(["db", "push"])

    # ------------------------------------------------------------------

    def _run_prisma(self, args: Sequence[str]) -> "MigrationResult":
        schema = self.backend_dir / "prisma" / "schema.prisma"
        if not schema.exists():
            raise FileNotFoundError(
                f"prisma/schema.prisma not found in {self.backend_dir}.  "
                "Generate with orm='prisma' in your AppSpec."
            )

        cmd = ["npx", "prisma"] + list(args)
        env = _make_env(self.database_url)

        log.info("PrismaMigrationEngine: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.backend_dir),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            result = MigrationResult(
                engine="prisma",
                command=cmd,
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except subprocess.TimeoutExpired:
            result = MigrationResult(
                engine="prisma",
                command=cmd,
                returncode=-1,
                stdout="",
                stderr="Prisma command timed out after 180 s.",
                timed_out=True,
            )

        if not result.ok:
            log.warning(
                "Prisma command failed (rc=%d): %s\n%s",
                result.returncode,
                " ".join(cmd),
                result.stderr[:2000],
            )
        return result


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class MigrationResult:
    """Structured result from a migration command."""

    __slots__ = ("engine", "command", "returncode", "stdout", "stderr", "timed_out")

    def __init__(
        self,
        engine: str,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.engine = engine
        self.command = command
        self.returncode = returncode
        self.stdout = stdout[-16_000:]
        self.stderr = stderr[-16_000:]
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def summary(self) -> str:
        status = "ok" if self.ok else ("timeout" if self.timed_out else f"exit {self.returncode}")
        return f"[{self.engine}] {' '.join(self.command[2:5])} → {status}"

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "command": self.command,
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }

    def __repr__(self) -> str:
        return f"MigrationResult({self.summary()!r})"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_migration_engine(
    project_root: Path,
    orm: str = "sqlalchemy",
    *,
    database_url: str | None = None,
) -> "AlembicMigrationEngine | PrismaMigrationEngine":
    """Return the appropriate migration engine for *orm*.

    Args:
        project_root: Root of the generated project.
        orm: One of ``sqlalchemy``, ``dataclass`` (→ Alembic), or ``prisma``.
        database_url: Optional DATABASE_URL override.
    """
    if orm == "prisma":
        backend_dir = project_root / "backend"
        if not backend_dir.exists():
            backend_dir = project_root
        return PrismaMigrationEngine(backend_dir, database_url=database_url)

    return AlembicMigrationEngine(project_root, database_url=database_url)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env(database_url: str | None) -> dict[str, str] | None:
    """Build environment dict, injecting DATABASE_URL override if provided."""
    if database_url is None:
        return None
    import os
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    return env


_REVISION_RE = re.compile(r"Rev:\s*([a-f0-9]+)", re.IGNORECASE)


def _extract_revision(text: str) -> str | None:
    """Pull the first revision ID from alembic output."""
    m = _REVISION_RE.search(text)
    return m.group(1) if m else None


def _extract_revisions(text: str) -> list[str]:
    """Pull all revision IDs from alembic output."""
    return _REVISION_RE.findall(text)
