"""Tavily AI Search integration for real-time UI/UX pattern research.

Fetches modern design patterns, TailwindCSS snippets, Lucide icons, and WCAG rules
to augment the prompt context before Nemotron code generation.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sketchforge.utilities.paths import repo_root

log = logging.getLogger(__name__)


class TavilyResearcher:
    """Outbound client for Tavily Search API."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "").strip()
        if not self.api_key:
            env_file = repo_root() / ".env"
            if env_file.is_file():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("TAVILY_API_KEY=") and not line.startswith("#"):
                        self.api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if self.api_key:
                            os.environ["TAVILY_API_KEY"] = self.api_key
                            break

        self._client: Any = None
        if self.api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not initialize TavilyClient: %s", exc)

    @property
    def is_available(self) -> bool:
        return bool(self._client)

    def search_ui_patterns(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Search for modern frontend components, CSS techniques, or API designs."""
        if not self._client:
            log.info("Tavily API key not set; providing curated modern UI design guidelines.")
            return self._curated_modern_patterns(query)

        search_query = f"modern web UI UX design implementation: {query}"
        try:
            response = self._client.search(
                query=search_query,
                search_depth="advanced",
                max_results=max_results,
                include_raw_content=False,
            )
            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", "")[:500],
                })
            return results if results else self._curated_modern_patterns(query)
        except Exception as exc:  # noqa: BLE001
            log.warning("Tavily search query failed (%s); using curated design patterns.", exc)
            return self._curated_modern_patterns(query)

    def _curated_modern_patterns(self, query: str) -> list[dict[str, str]]:
        """High-aesthetic modern design token recommendations for Nemotron code generation."""
        return [
            {
                "title": "Modern Dark Glassmorphic Design System",
                "url": "https://tailwindcss.com/docs",
                "content": "Deep dark aesthetic (background: #09090c, cards: #141419, borders: 1px solid rgba(255,255,255,0.08)). Accent: vibrant emerald/indigo (#10b981 / #6366f1). Use backdrop-filter: blur(12px) for glass cards.",
            },
            {
                "title": "WCAG AA Accessible Typography & Spacing",
                "url": "https://www.w3.org/WAI/WCAG21/quickref/",
                "content": "Ensure high-contrast text ratios (>= 4.5:1). Clean modern system font stack (Inter, -apple-system, Segoe UI, sans-serif) with responsive fluid sizing and 8px grid spacing.",
            },
            {
                "title": "Micro-Animations & Interactive Feedback",
                "url": "https://lucide.dev/",
                "content": "Subtle hover lift (transform: translateY(-2px)), smooth transitions (transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1)), live pulse indicators for real-time status badges, and SVG icon accents.",
            },
        ]

    def build_research_context(self, user_prompt: str) -> str:
        """Construct a formatted research summary to inject into the Nemotron prompt."""
        findings = self.search_ui_patterns(user_prompt)
        if not findings:
            return ""

        lines = ["\n### Live Web UI Research (via Tavily Search):"]
        for f in findings:
            lines.append(f"- **{f['title']}**: {f['content']} ({f['url']})")
        lines.append("")
        return "\n".join(lines)
