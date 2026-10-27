"""Tavily AI Search integration for real-time UI/UX pattern research.

Fetches modern design patterns, TailwindCSS snippets, Lucide icons, and WCAG rules
to augment the prompt context before Nemotron code generation.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


class TavilyResearcher:
    """Outbound client for Tavily Search API."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
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
            log.info("Tavily API key not set; skipping live search research.")
            return []

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
            return results
        except Exception as exc:  # noqa: BLE001
            log.warning("Tavily search query failed: %s", exc)
            return []

    def build_research_context(self, user_prompt: str) -> str:
        """Construct a formatted research summary to inject into the Nemotron prompt."""
        if not self.is_available:
            return ""

        findings = self.search_ui_patterns(user_prompt)
        if not findings:
            return ""

        lines = ["\n### Live Web UI Research (via Tavily Search):"]
        for f in findings:
            lines.append(f"- **{f['title']}**: {f['content']} ({f['url']})")
        lines.append("")
        return "\n".join(lines)
