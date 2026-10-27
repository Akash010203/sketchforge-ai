"""Dense cosine vector index with optional caller-supplied embedding function.

The built-in signed feature-hash embedding is deterministic and dependency-free. For semantic
search, pass a local embedding function; no model or network access is performed automatically.
"""
from __future__ import annotations

import hashlib
import math
import re

TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9-]*|\d+(?:\.\d+)*")


class VectorIndex:
    def __init__(self, documents=(), embedding_fn=None, dimensions: int = 2048):
        if dimensions < 32:
            raise ValueError("dimensions must be >= 32")
        self.embedding_fn = embedding_fn
        self.dimensions = dimensions
        self.documents = []
        self.vectors = []
        self.add_documents(documents)

    def _embed(self, text):
        import numpy as np
        if self.embedding_fn:
            vector = np.asarray(self.embedding_fn(text), dtype=np.float32).reshape(-1)
        else:
            vector = np.zeros(self.dimensions, dtype=np.float32)
            tokens = [t.lower() for t in TOKEN.findall(text)]
            tokens.extend(f"{a}_{b}" for a, b in zip(tokens, tokens[1:]))
            for token in tokens:
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[idx] += sign * (1 + math.log1p(len(token)))
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def add_documents(self, documents):
        for doc in documents:
            vector = self._embed(doc.text)
            if self.vectors and vector.shape != self.vectors[0].shape:
                raise ValueError("Embedding dimensions changed within the index")
            self.documents.append(doc)
            self.vectors.append(vector)

    def search(self, query: str, top_k: int = 10, filters: dict | None = None):
        if top_k <= 0 or not self.documents:
            return []
        query_vector = self._embed(query)
        results = []
        for doc, vector in zip(self.documents, self.vectors):
            if filters and any(doc.metadata.get(k) != v for k, v in filters.items()):
                continue
            score = float(vector @ query_vector) if vector.shape == query_vector.shape else 0.0
            results.append({"document": doc, "score": score})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]
