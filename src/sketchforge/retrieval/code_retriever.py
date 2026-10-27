"""Code pattern retriever: wires HybridRetriever into the generation pipeline."""
from __future__ import annotations

import logging
from typing import Optional

from sketchforge.retrieval.document_loader import Document
from sketchforge.retrieval.patterns import PATTERN_CATALOG
from sketchforge.retrieval.retriever import HybridRetriever

log = logging.getLogger(__name__)

_RETRIEVER_INSTANCE: Optional[HybridRetriever] = None


def get_pattern_retriever() -> HybridRetriever:
    """Return a singleton HybridRetriever indexed with verified code patterns."""
    global _RETRIEVER_INSTANCE
    if _RETRIEVER_INSTANCE is None:
        docs = []
        for entry in PATTERN_CATALOG:
            full_text = f"File: {entry['path']}\nTags: {entry['tags']}\n\n{entry['text']}"
            doc = Document(
                id=entry["id"],
                text=full_text,
                source=entry["path"],
                metadata={
                    "path": entry["path"],
                    "tags": entry["tags"],
                    "extension": entry.get("extension", ""),
                    "code": entry["text"],
                },
            )
            docs.append(doc)
        _RETRIEVER_INSTANCE = HybridRetriever(docs)
    return _RETRIEVER_INSTANCE


def retrieve_code_pattern(path_hint: str, description: str, top_k: int = 1) -> str | None:
    """Search for the most relevant verified pattern matching a path and description.

    Returns the raw code string, or None if no suitable pattern was found.
    """
    try:
        from pathlib import Path
        ext = Path(path_hint).suffix.lower()
        filters = {"extension": ext} if ext in {".py", ".css", ".js", ".sql", ".html"} else None

        retriever = get_pattern_retriever()
        query = f"{path_hint} {description}"
        results = retriever.search(query, top_k=top_k, filters=filters)
        if not results:
            # Fall back without extension filter if strict filter found nothing
            results = retriever.search(query, top_k=top_k)
        if not results:
            return None
        best_doc = results[0]["document"]
        return best_doc.metadata.get("code")
    except Exception as exc:  # noqa: BLE001
        log.warning("Pattern retrieval error: %s", exc)
        return None
    return None
