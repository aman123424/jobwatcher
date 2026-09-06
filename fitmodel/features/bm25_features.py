"""
fitmodel/features/bm25_features.py
=====================================

Lexical (BM25) resume-vs-JD scoring. Resume "chunks" (one bullet per
chunk - see pipeline.py::load_resume_chunks()) are the documents;
a JD's text (full, and separately its Required-section text) is the
query. BM25Okapi gives one score per resume chunk for a given query -
max() and the mean of the top 3 are what actually feed the model
(a single global mean would dilute a strong match against one bullet
with 30+ unrelated ones, the same reasoning the regex scorer already
uses per-skill rather than whole-document).
"""

import re

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class ResumeBM25Index:
    def __init__(self, resume_chunks: list[dict]):
        self.chunks = resume_chunks
        self._index = BM25Okapi([tokenize(c["text"]) for c in resume_chunks])

    def scores_for(self, query_text: str) -> list[float]:
        return list(self._index.get_scores(tokenize(query_text)))

    def max_and_top3_mean(self, query_text: str) -> tuple[float, float]:
        scores = self.scores_for(query_text)
        if not scores:
            return 0.0, 0.0
        top3 = sorted(scores, reverse=True)[:3]
        return max(scores), sum(top3) / len(top3)
