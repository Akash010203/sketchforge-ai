"""Convenience root entry point delegating to sketchforge.__main__."""

from __future__ import annotations

from sketchforge.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
