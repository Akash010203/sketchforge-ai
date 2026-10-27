"""Metadata predicates shared by retrieval callers."""
from __future__ import annotations


def matches_metadata(document, filters: dict | None) -> bool:
    if not filters:
        return True
    metadata = getattr(document, "metadata", {})
    return all(metadata.get(key) == value for key, value in filters.items())
