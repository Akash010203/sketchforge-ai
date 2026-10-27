"""Small dependency-free BM25 index."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9-]*|\d+(?:\.\d+)*")


def _tokens(text):
    return [t.lower() for t in TOKEN.findall(text)]


class LexicalIndex:
    def __init__(self, documents=(), k1: float = 1.5, b: float = .75):
        self.k1, self.b = k1, b
        self.documents = []
        self.term_freq = []
        self.postings = defaultdict(list)
        self.add_documents(documents)

    def add_documents(self, documents):
        start = len(self.documents)
        for doc in documents:
            tokens = _tokens(doc.text)
            tf = Counter(tokens)
            idx = len(self.documents)
            self.documents.append(doc)
            self.term_freq.append(tf)
            for term, count in tf.items():
                self.postings[term].append((idx, count))
        if len(self.documents) < start:
            raise RuntimeError("Index size invariant violated")

    def search(self, query: str, top_k: int = 10, filters: dict | None = None):
        if top_k <= 0:
            return []
        terms = _tokens(query)
        n_docs = len(self.documents)
        avg_len = sum(sum(tf.values()) for tf in self.term_freq) / max(n_docs, 1)
        scores = defaultdict(float)
        lengths = [sum(tf.values()) for tf in self.term_freq]
        for term in terms:
            posting = self.postings.get(term, [])
            idf = math.log(1 + (n_docs - len(posting) + .5) / (len(posting) + .5))
            for idx, freq in posting:
                norm = freq + self.k1 * (1 - self.b + self.b * lengths[idx] / max(avg_len, 1))
                scores[idx] += idf * freq * (self.k1 + 1) / norm
        results = []
        for idx, score in scores.items():
            doc = self.documents[idx]
            if filters and any(doc.metadata.get(k) != v for k, v in filters.items()):
                continue
            results.append({"document": doc, "score": score})
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]
