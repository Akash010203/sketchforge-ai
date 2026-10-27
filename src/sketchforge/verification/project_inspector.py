"""Project inspector: validates the generated file tree before execution."""
from __future__ import annotations

from pathlib import Path


REQUIRED_REACT_TS = [
    "package.json",
    "tsconfig.json",
    "index.html",
    "src/main.tsx",
    "src/App.tsx",
    "src/styles/global.css",
]

REQUIRED_HTML_CSS = [
    "css/style.css",
    "README.md",
]


def inspect_project(root: Path) -> dict:
    """Check the generated project for expected files and return a status dict."""
    present: list[str] = []
    missing: list[str] = []

    # Detect tech stack from presence of package.json
    if (root / "package.json").exists():
        required = REQUIRED_REACT_TS
        stack = "react-ts"
    else:
        required = REQUIRED_HTML_CSS
        stack = "html-css-js"

    for rel in required:
        if (root / rel).is_file():
            present.append(rel)
        else:
            missing.append(rel)

    all_files = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "node_modules" not in str(p)
    )

    return {
        "stack": stack,
        "root": str(root),
        "total_files": len(all_files),
        "required_present": present,
        "required_missing": missing,
        "all_files": all_files,
        "ok": len(missing) == 0,
    }
