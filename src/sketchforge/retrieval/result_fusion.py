"""Reciprocal-rank fusion for combining lexical and vector retrieval lists."""
from __future__ import annotations


def reciprocal_rank_fusion(*ranked_lists, top_k: int = 10, k: int = 60):
    scores = {}
    docs = {}
    for result_list in ranked_lists:
        for rank, result in enumerate(result_list, start=1):
            doc = result["document"]
            key = doc.id
            docs[key] = doc
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores, key=scores.get, reverse=True)[:max(0, top_k)]
    return [{"document": docs[key], "score": scores[key]} for key in ordered]
