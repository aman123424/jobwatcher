"""
fitmodel/suggestions/corpus_stats.py
=======================================

CONFIRMED REAL BUG, found via this module's own Phase-2 spot-check
(exactly the check the implementation plan called for), in two rounds:

  1. Plain per-JD term-frequency counting surfaced "microsoft",
     "background check" and generic filler ("engineering", "design",
     "workflows") as if they were emphasized SKILLS - just words that
     repeat often in one posting's own boilerplate, or across nearly
     every posting, not signal.
  2. Switching to tf-idf against the full 312-JD training_examples
     corpus (rarity-weighted, not raw count) fixed some of that but
     kept surfacing plain generic English words - "requirements",
     "discipline", "proven", "specialized" - which are individually
     rare-ish across the corpus (so tf-idf ranks them high) without
     being remotely close to a skill. IDF measures RARITY, not
     "is this a skill" - no amount of stoplist patching closes that
     gap for open-vocabulary n-gram extraction on messy real JD text.

Fix: give TfidfVectorizer an EXPLICIT vocabulary (skill_vocabulary.py)
- candidates outside that curated skill/tech list are never extracted
at all, full stop. IDF still ranks WITHIN that vocabulary (so a rare,
specific skill outranks a common one), fit once over the 312-JD corpus
and cached to disk (fitmodel/models/corpus_tfidf.joblib) since
re-fitting per call/run is unnecessary repeated work.
"""

from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer

from features._backend_path import ensure_backend_on_path
from features.jd_sections import clean_jd_text, required_section_text

from .skill_vocabulary import build_vocabulary

CACHE_PATH = Path(__file__).parent.parent / "models" / "corpus_tfidf.joblib"

ensure_backend_on_path()


def _fit_vectorizer() -> TfidfVectorizer:
    from dbconn import SessionLocal, TrainingExample

    db = SessionLocal()
    try:
        jd_texts = [r.jd_text for r in db.query(TrainingExample).all()]
    finally:
        db.close()

    required_texts = [required_section_text(clean_jd_text(text)) for text in jd_texts]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), vocabulary=sorted(build_vocabulary()))
    vectorizer.fit(required_texts)
    return vectorizer


_vectorizer: TfidfVectorizer | None = None


def get_vectorizer() -> TfidfVectorizer:
    global _vectorizer
    if _vectorizer is not None:
        return _vectorizer

    if CACHE_PATH.exists():
        _vectorizer = joblib.load(CACHE_PATH)
        return _vectorizer

    _vectorizer = _fit_vectorizer()
    CACHE_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(_vectorizer, CACHE_PATH)
    return _vectorizer


def top_terms(required_text: str, top_n: int) -> list[tuple[str, float]]:
    """
    Ranks terms in `required_text` by tf-idf, restricted to
    skill_vocabulary.py's curated list - a term outside that vocabulary
    is never a candidate at all, regardless of how often it repeats.
    """
    vectorizer = get_vectorizer()
    if not required_text.strip():
        return []
    row = vectorizer.transform([required_text])
    terms = vectorizer.get_feature_names_out()
    scores = row.toarray()[0]
    ranked = sorted(((terms[i], scores[i]) for i in scores.nonzero()[0]), key=lambda t: -t[1])
    return ranked[:top_n]
