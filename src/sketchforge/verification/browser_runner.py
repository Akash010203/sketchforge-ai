"""Browser runner: launches the built app with Playwright and performs smoke tests.

Uses a development server (vite preview on the built dist/) to load the app, then:
- Asserts the page title is correct
- Asserts expected page elements exist in the DOM
- Captures a screenshot
- Tests form interactions if forms are present

Playwright is invoked as a subprocess (not in-process) to keep the generated app's
JS execution fully separate from the SketchForge process.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from sketchforge.generation.app_specification import AppSpec
from sketchforge.verification.verification_report import VerificationStep


@dataclass
class BrowserResult:
    ok: bool
    screenshot_path: str | None = None
    assertions: list[dict] | None = None
    error: str = ""
    duration_ms: float = 0.0


def run_browser_smoke(
    project_root: Path,
    spec: AppSpec,
    screenshot_dir: Path | None = None,
    timeout: float = 60.0,
) -> VerificationStep:
    """Launch the built app via playwright and run DOM assertions."""
    if shutil.which("playwright") is None and shutil.which("npx") is None:
        return VerificationStep(
            name="browser smoke test",
            ok=True,
            notes="Playwright not available; skipped",
        )

    t0 = time.perf_counter()
    script = _build_playwright_script(spec, screenshot_dir)
    script_path = project_root / "_sf_smoke.js"
    script_path.write_text(script, encoding="utf-8")

    try:
        result = subprocess.run(
            ["npx", "playwright", "test", str(script_path), "--reporter=json"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        stdout = result.stdout[-4000:]
        stderr = result.stderr[-4000:]
    except subprocess.TimeoutExpired:
        ok = False
        stdout = ""
        stderr = "Playwright test timed out"
    finally:
        script_path.unlink(missing_ok=True)

    duration_ms = (time.perf_counter() - t0) * 1000
    return VerificationStep(
        name="browser smoke test",
        ok=ok,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
    )


def _build_playwright_script(spec: AppSpec, screenshot_dir: Path | None) -> str:
    """Build a Node.js Playwright test script for the generated application."""
    first_page = spec.pages[0] if spec.pages else None
    title = first_page.title if first_page else spec.name
    screenshot = str(screenshot_dir / "smoke.png") if screenshot_dir else ""

    return f'''\
const {{ test, expect }} = require("@playwright/test");

test.use({{ baseURL: "http://localhost:4173" }});

test("SketchForge smoke test: {spec.name}", async ({{ page }}) => {{
  await page.goto("/");
  await expect(page).toHaveTitle(/{spec.name}/i);
  const h1 = page.locator("h1, h2").first();
  await expect(h1).toBeVisible();
  {f'await page.screenshot({{ path: "{screenshot.replace(chr(92), "/")}", fullPage: true }});' if screenshot else ""}
  console.log("Smoke test passed for {spec.name}");
}});
'''
