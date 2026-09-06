"""
fitmodel/features/embedding_features.py
==========================================

Dense (sentence-embedding) resume-vs-JD scoring - catches semantic
matches BM25 can't (e.g. "built REST services" vs "developed web
APIs", no shared tokens at all). Uses all-MiniLM-L6-v2 (~80MB, CPU-
friendly, no API/network call at inference time - matches the
explicit "no LLM calls" requirement) via sentence-transformers.

The model is loaded ONCE as a module-level singleton - re-loading it
per call would turn a sub-second operation into a multi-second one on
every single feature-vector build, silently dominating training/
scoring runtime.

MiniLM truncates at 256 tokens - a full multi-page JD can lose its own
Required section to truncation if embedded whole, which is exactly why
pipeline.py embeds the Required-section text SEPARATELY rather than
relying on the full-JD embedding alone to carry that signal.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    return _get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)


def cosine_sims(query_embedding: np.ndarray, chunk_embeddings: np.ndarray) -> np.ndarray:
    # Both sides are already L2-normalized (normalize_embeddings=True
    # above), so a plain dot product IS cosine similarity - no need for
    # sklearn's cosine_similarity here.
    return chunk_embeddings @ query_embedding


def max_and_top3_mean(sims: np.ndarray) -> tuple[float, float]:
    if sims.size == 0:
        return 0.0, 0.0
    top3 = np.sort(sims)[::-1][:3]
    return float(sims.max()), float(top3.mean())


class ResumeEmbeddingIndex:
    def __init__(self, resume_chunks: list[dict]):
        self.chunks = resume_chunks
        self.chunk_embeddings = embed([c["text"] for c in resume_chunks])

    def max_and_top3_mean_sim(self, query_text: str) -> tuple[float, float]:
        query_embedding = embed([query_text])[0]
        sims = cosine_sims(query_embedding, self.chunk_embeddings)
        return max_and_top3_mean(sims)
