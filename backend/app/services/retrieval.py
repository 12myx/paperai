"""Hybrid retrieval: BM25 over terms plus hashed character n-gram cosine.

The default deployment deliberately avoids a heavyweight embedding model: the
hybrid lexical index is fast, deterministic, offline and works for mixed
Chinese/English papers. The interface is embedding-shaped so a neural index
can be added without changing callers.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}", re.I)
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "not", "but", "they", "their", "which", "using", "used",
    "can", "our", "these", "such", "also", "into", "than", "more", "may",
    "we", "is", "of", "to", "in", "on", "by", "as", "an", "at", "it", "be",
    "本文", "我们", "研究", "方法", "结果", "以及", "可以", "进行", "通过",
}
HASH_DIM = 512


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = [t for t in TOKEN_RE.findall(lowered) if t not in STOPWORDS]
    cjk = [ch for ch in lowered if "\u4e00" <= ch <= "\u9fff"]
    tokens.extend(cjk)
    tokens.extend("".join(pair) for pair in zip(cjk, cjk[1:]))
    return tokens


def _ngram_vector(text: str) -> np.ndarray:
    vector = np.zeros(HASH_DIM, dtype=np.float32)
    cleaned = re.sub(r"\s+", " ", text.lower())
    for i in range(len(cleaned) - 2):
        gram = cleaned[i : i + 3]
        if gram.strip():
            vector[hash(gram) % HASH_DIM] += 1.0
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


@dataclass
class Document:
    chunk_id: str
    paper_id: str
    paper_title: str
    page_start: int
    page_end: int
    section: str
    text: str
    tags: list[str]


class HybridIndex:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.token_counts = [self._counts(tokenize(d.text)) for d in documents]
        self.lengths = [sum(c.values()) or 1 for c in self.token_counts]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        self.df: dict[str, int] = {}
        for counts in self.token_counts:
            for term in counts:
                self.df[term] = self.df.get(term, 0) + 1
        self.vectors = [_ngram_vector(d.text) for d in documents]
        self.title_counts = [self._counts(tokenize(d.paper_title)) for d in documents]

    @staticmethod
    def _counts(tokens: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for token in tokens:
            out[token] = out.get(token, 0) + 1
        return out

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (len(self.documents) - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 8) -> list[tuple[Document, float]]:
        if not self.documents:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        q_terms = set(query_tokens)
        k1, b = 1.4, 0.72
        bm25 = np.zeros(len(self.documents), dtype=np.float32)
        for index, counts in enumerate(self.token_counts):
            length = self.lengths[index]
            score = 0.0
            for term in q_terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                denom = freq + k1 * (1 - b + b * length / self.avg_len)
                score += self._idf(term) * freq * (k1 + 1) / denom
            title_hits = sum(1 for term in q_terms if self.title_counts[index].get(term))
            bm25[index] = score + 0.35 * title_hits

        q_vec = _ngram_vector(query)
        cosine = np.array([float(np.dot(q_vec, vec)) for vec in self.vectors], dtype=np.float32)

        def _norm(values: np.ndarray) -> np.ndarray:
            peak = float(values.max()) if values.size else 0.0
            return values / peak if peak > 0 else values

        combined = 0.68 * _norm(bm25) + 0.32 * _norm(cosine)
        lowered_query = query.lower().strip()
        if len(lowered_query) >= 6:
            for index, document in enumerate(self.documents):
                if lowered_query in document.text.lower():
                    combined[index] += 0.25

        order = np.argsort(-combined)[: max(top_k * 2, top_k)]
        results: list[tuple[Document, float]] = []
        for index in order:
            if combined[index] <= 0.02:
                continue
            results.append((self.documents[int(index)], float(combined[int(index)])))
            if len(results) >= top_k:
                break
        return results
