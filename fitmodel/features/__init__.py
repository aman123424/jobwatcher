"""
fitmodel/features
==================

Turns a (resume, job description) pair into one flat numeric feature
vector for the models in fitmodel/training - see pipeline.py for the
actual combination. Split by concern the same way backend/scoring/ is:

    jd_sections.py         - thin adapter over backend/scoring's
                              Required/Preferred section detection
    bm25_features.py       - lexical (BM25) resume-vs-JD scoring
    embedding_features.py  - dense (sentence-transformer) resume-vs-JD
                              scoring
    engineered_features.py - adapter over backend/scoring's hard-filter
                              GATES (years/degree/title/competing-stack)
                              and per-tier skill-match counts - NOT the
                              regex scorer's own final weighted score,
                              see pipeline.py's own docstring for why.
    pipeline.py             - build_feature_vector(), FEATURE_NAMES,
                              load_resume_chunks()
"""

from .pipeline import FEATURE_NAMES, FeatureExtractor, build_feature_vector, load_resume_chunks

__all__ = ["build_feature_vector", "FeatureExtractor", "FEATURE_NAMES", "load_resume_chunks"]
