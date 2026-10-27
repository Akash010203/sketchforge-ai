"""Resource limits for sandbox processes.

Uses platform-specific mechanisms to apply soft CPU time and memory bounds.
On Windows, these are implemented via Job Objects (via pywin32 if available)
or subprocess timeout; on POSIX, via resource.setrlimit.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass
class ResourceLimits:
    cpu_seconds: int = 120         # wall-clock timeout in seconds
    max_output_bytes: int = 32_768  # stdout + stderr cap each


# Singleton defaults
DEFAULT = ResourceLimits()


def describe() -> dict:
    """Describe what resource limiting is available on this platform."""
    info = {"platform": sys.platform}
    if sys.platform == "win32":
        try:
            import win32job  # type: ignore[import]
            info["mechanism"] = "win32job (Job Objects)"
        except ImportError:
            info["mechanism"] = "subprocess timeout only (install pywin32 for memory limits)"
    else:
        try:
            import resource  # type: ignore[import]
            info["mechanism"] = "POSIX resource.setrlimit"
        except ImportError:
            info["mechanism"] = "subprocess timeout only"
    return info
