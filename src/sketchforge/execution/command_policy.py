"""Command policy: strict allow-list for sandbox command execution.

Generated code must not receive unrestricted access to the host machine.
Every subprocess command that may run in the sandbox is explicitly listed here.
Anything not on the list is refused with a clear error.
"""
from __future__ import annotations

import re
import shutil
from typing import Sequence


class CommandNotPermitted(RuntimeError):
    """Raised when a command is not on the allow-list."""


# ---------------------------------------------------------------------------
# Allow-list entries
# ---------------------------------------------------------------------------
# Each entry is a tuple of (match_type, value):
#   ("exe",   "npm")             — matches if argv[0] basename == "npm"
#   ("regex", r"npm\.(cmd|ps1)") — matches argv[0] against a regex
#   ("argv",  ("npm", "install")) — matches argv[0:N] exactly
# ---------------------------------------------------------------------------

_ALLOWED: list[tuple[str, object]] = [
    # Node / npm
    ("exe",   "npm"),
    ("exe",   "npx"),
    ("exe",   "node"),
    # Python tooling (for generated Python backends)
    ("exe",   "python"),
    ("exe",   "python3"),
    ("exe",   "pytest"),
    ("exe",   "pip"),
    # Static analysis (read-only, no network)
    ("exe",   "ruff"),
    ("exe",   "eslint"),
    ("exe",   "tsc"),
    # Playwright CLI (headless browser tests only)
    ("argv",  ("npx", "playwright")),
    ("argv",  ("python", "-m", "pytest")),
    ("argv",  ("python3", "-m", "pytest")),
    # Windows variants
    ("regex", r"npm\.(cmd|ps1)$"),
    ("regex", r"npx\.(cmd|ps1)$"),
    ("regex", r"node\.(exe)$"),
    ("regex", r"python\.(exe)$"),
    ("regex", r"python3\.(exe)$"),
]

# Specific sub-commands that are *blocked* even if the executable is allowed.
# Order matters: these are evaluated before the allow-list.
_BLOCKED_ARGV: list[tuple] = [
    ("npm", "publish"),
    ("npm", "unpublish"),
    ("pip", "install", "--index-url"),   # no custom indexes
    ("npx", "exec"),
    ("node", "-e"),                       # arbitrary inline eval
    # ------------------------------------------------------------------ #
    # SECURITY: Block inline Python code strings unconditionally.        #
    # `python -c` and `python3 -c` allow arbitrary code execution and    #
    # must never be permitted inside the sandbox regardless of the       #
    # allow-list entry for the python/python3 executable.                #
    # ------------------------------------------------------------------ #
    ("python",  "-c"),
    ("python3", "-c"),
]


def is_permitted(cmd: Sequence[str]) -> bool:
    """Return True if the command is on the allow-list."""
    if not cmd:
        return False

    exe = _basename(str(cmd[0]))

    # Check blocked argv first (overrides allow-list)
    for blocked in _BLOCKED_ARGV:
        if len(cmd) >= len(blocked) and tuple(str(x).lower() for x in cmd[: len(blocked)]) == blocked:
            return False

    # Check allow-list
    for match_type, value in _ALLOWED:
        if match_type == "exe" and exe == value:
            return True
        if match_type == "regex" and re.search(str(value), str(cmd[0]), re.IGNORECASE):
            return True
        if match_type == "argv":
            prefix = tuple(value)  # type: ignore[arg-type]
            if len(cmd) >= len(prefix):
                if tuple(str(x).lower() for x in cmd[: len(prefix)]) == tuple(x.lower() for x in prefix):
                    return True

    return False


def assert_permitted(cmd: Sequence[str]) -> None:
    """Raise CommandNotPermitted if the command is not allowed."""
    if not is_permitted(cmd):
        raise CommandNotPermitted(
            f"Command not permitted in sandbox: {' '.join(str(x) for x in cmd[:4])!r}\n"
            "Allowed executables: npm, npx, node, python (module mode), pytest, ruff, eslint, tsc.\n"
            "Blocked regardless of allow-list: python -c, python3 -c, node -e, npx exec."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _basename(path: str) -> str:
    """Normalised lowercase basename without extension."""
    import os.path
    base = os.path.basename(path).lower()
    # Strip common Windows extensions
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if base.endswith(ext):
            base = base[: -len(ext)]
    return base
