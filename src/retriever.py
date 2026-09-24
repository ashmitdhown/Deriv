"""Knowledge-base retrieval. Default: local TF-IDF + cosine similarity (scikit-learn), deterministic.

TF-IDF is lexical: it can be gamed by keyword stuffing and misses synonyms. It is NOT a
security control; the relevance threshold only stops obviously irrelevant articles being
presented as evidence. Downstream grounding checks and escalation handle the rest.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from src.config import Settings, settings
from src.models import Article, Hit, RetrievalResult
from src.utils import normalize_text


class Retriever(ABC):
    @abstractmethod
    def index(self, articles: list[Article]) -> None: ...

    @abstractmethod
    def search(self, query: str, k: int | None = None) -> RetrievalResult: ...


class TfidfRetriever(Retriever):
    def __init__(self, cfg: Settings = settings):
        self.cfg = cfg
        self._ids: list[str] = []
        self._vec: TfidfVectorizer | None = None
        self._matrix = None

    def index(self, articles: list[Article]) -> None:
        # Sort by id so the index (and therefore every score) is independent of file order.
        ordered = sorted(articles, key=lambda a: a.article_id)
        self._ids = [a.article_id for a in ordered]
        # Title repeated once to give it a little extra weight.
        docs = [f"{a.title}. {a.title}. {a.body}" for a in ordered]
        self._vec = TfidfVectorizer(
            lowercase=True, stop_words="english", ngram_range=(1, 2), sublinear_tf=True,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9]+\b", norm="l2", dtype=np.float64,
        )
        self._matrix = self._vec.fit_transform(docs) if docs else None

    def search(self, query: str, k: int | None = None) -> RetrievalResult:
        k = max(1, min(3, k if k is not None else self.cfg.top_k))
        query = normalize_text(query or "")
        if self._vec is None or self._matrix is None or len(query) < self.cfg.min_query_chars:
            return RetrievalResult(hits=[], sufficient=False, best_score=0.0)

        q = self._vec.transform([query])
        if q.nnz == 0:  # no known vocabulary in the query
            return RetrievalResult(hits=[], sufficient=False, best_score=0.0)
        sims = linear_kernel(q, self._matrix).ravel()
        # Round to kill float noise, then stable tie-break on article_id.
        ranked = sorted(((round(float(s), 6), aid) for aid, s in zip(self._ids, sims)), key=lambda t: (-t[0], t[1]))
        best_score, best_id = ranked[0]

        passing = [Hit(aid, s) for s, aid in ranked if s >= self.cfg.min_relevance]
        if not passing:
            return RetrievalResult(hits=[], sufficient=False, best_score=best_score,
                                   weak_candidate=best_id if best_score > 0 else None)
        # Keep secondary hits only if reasonably close to the best, so weak matches aren't padded in.
        cutoff = passing[0].score * self.cfg.relative_cutoff
        hits = [h for i, h in enumerate(passing) if i == 0 or h.score >= cutoff][:k]
        return RetrievalResult(hits=hits, sufficient=True, best_score=best_score)
