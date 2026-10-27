"""Recall@k and reciprocal-rank evaluation for small retrieval judgments."""
from __future__ import annotations


def evaluate_retrieval(search_fn, queries: dict[str, set[str]], ks=(1, 5, 10)) -> dict:
    """Evaluate ``query -> relevant document IDs`` judgments using a search callable."""
    if not queries:
        raise ValueError("queries must contain at least one judged query")
    max_k = max(ks)
    recalls = {int(k): [] for k in ks}
    reciprocal_ranks = []
    for query, relevant in queries.items():
        if not relevant:
            continue
        hits = search_fn(query, top_k=max_k)
        ids = [item["document"].id for item in hits]
        first = next((i + 1 for i, doc_id in enumerate(ids) if doc_id in relevant), None)
        reciprocal_ranks.append(1.0 / first if first else 0.0)
        for k in ks:
            recalls[int(k)].append(len(set(ids[:k]) & relevant) / len(relevant))
    if not reciprocal_ranks:
        raise ValueError("no query has relevant document IDs")
    return {"mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "recall_at_k": {k: sum(v) / len(v) for k, v in recalls.items()},
            "query_count": len(reciprocal_ranks)}
