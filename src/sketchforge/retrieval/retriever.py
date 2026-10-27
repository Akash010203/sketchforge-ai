"""Hybrid lexical/vector retriever for local project knowledge."""
from __future__ import annotations

from sketchforge.retrieval.lexical_index import LexicalIndex
from sketchforge.retrieval.result_fusion import reciprocal_rank_fusion
from sketchforge.retrieval.vector_index import VectorIndex


class HybridRetriever:
    def __init__(self, documents=(), embedding_fn=None):
        self.lexical = LexicalIndex(documents)
        self.vector = VectorIndex(documents, embedding_fn=embedding_fn)

    def search(self, query: str, top_k: int = 10, filters: dict | None = None):
        lexical = self.lexical.search(query, top_k=top_k * 3, filters=filters)
        vector = self.vector.search(query, top_k=top_k * 3, filters=filters)
        return reciprocal_rank_fusion(lexical, vector, top_k=top_k)
