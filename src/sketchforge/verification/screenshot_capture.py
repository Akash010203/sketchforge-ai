"""Screenshot capture using Playwright or Pillow fallback."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


def capture_screenshot(url: str, output_path: Path, timeout: float = 30.0) -> bool:
    """Capture a full-page screenshot of ``url`` and save to ``output_path``.

    Uses playwright CLI if available, otherwise returns False.
    Returns True if the screenshot was written successfully.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not (shutil.which("npx") or shutil.which("playwright")):
        return False
    try:
        result = subprocess.run(
            [
                "npx", "playwright", "screenshot",
                "--full-page",
                "--browser", "chromium",
                url,
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0 and output_path.exists()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
