"""
fitmodel/suggestions/tailoring.py
====================================

Deterministic resume-tailoring suggestions - NO ML model, NO LLM call.
Given a JD's Required-section text, finds its own most emphasized
terms (plain term-frequency counting, not a learned/generative model)
and classifies each against Aman's actual resume:

  - TRUE GAP: the term matches nothing in RESUME_SKILLS at all.
  - UNVERIFIED: it matches a RESUME_SKILLS keyword that isn't in
    EVIDENTIAL_SKILLS - the skill is listed on the resume, but with no
    real bullet demonstrating it.
  - WORDING MISMATCH: it matches nothing literally, but its embedding
    is close to a resume chunk describing a related concept in
    different words (e.g. JD says "REST API framework", resume says
    "FastAPI") - reuses the SAME embedding model features/pipeline.py
    already loads, rather than a second copy.

Every message is a static f-string template - there is no free-text
generation anywhere in this module.
"""

from features import embedding_features
from features._backend_path import ensure_backend_on_path
from features.jd_sections import clean_jd_text, required_section_text

from . import corpus_stats

ensure_backend_on_path()

from scoring.resume_data import EVIDENTIAL_SKILLS, RESUME_CONTEXT, RESUME_SKILLS, _KEYWORD_PATTERNS  # noqa: E402

TOP_N_TERMS = 10
SYNONYM_SIMILARITY_THRESHOLD = 0.6


def _matching_resume_keyword(term: str) -> str | None:
    for keyword in RESUME_SKILLS:
        if _KEYWORD_PATTERNS[keyword].search(term):
            return keyword
    return None


def suggest(resume_chunks: list[dict], jd_text: str, embedding_index: embedding_features.ResumeEmbeddingIndex | None = None) -> list[dict]:
    haystack = clean_jd_text(jd_text)
    required_text = required_section_text(haystack)
    # tf-idf against the 312-JD training_examples corpus, not a raw
    # per-document count - see corpus_stats.py's own docstring for the
    # real spurious-term bug ("microsoft", "background check", generic
    # filler) this replaced.
    ranked_terms = corpus_stats.top_terms(required_text, TOP_N_TERMS)
    if not ranked_terms:
        return []

    index = embedding_index or embedding_features.ResumeEmbeddingIndex(resume_chunks)

    suggestions = []
    for term, _tfidf_score in ranked_terms:
        keyword = _matching_resume_keyword(term)

        if keyword and keyword in EVIDENTIAL_SKILLS:
            continue  # already well covered - nothing to suggest

        if keyword:
            context = RESUME_CONTEXT.get(keyword)
            message = f"JD emphasizes '{term}' (distinctive term in the Required section); your resume lists it without a demonstrating bullet - consider adding one."
            if context:
                message += f" (Closest existing mention: {context})"
            suggestions.append({"type": "unverified", "jd_term": term, "resume_key": keyword, "message": message})
            continue

        term_embedding = embedding_features.embed([term])[0]
        sims = embedding_features.cosine_sims(term_embedding, index.chunk_embeddings)
        best_idx = int(sims.argmax()) if sims.size else None
        if best_idx is not None and sims[best_idx] >= SYNONYM_SIMILARITY_THRESHOLD:
            resume_wording = index.chunks[best_idx]["text"]
            message = f"JD says '{term}'; your resume describes a related concept differently ('{resume_wording}') - consider adding '{term}' as an explicit phrasing too."
            suggestions.append({"type": "wording_mismatch", "jd_term": term, "resume_key": None, "message": message})
        else:
            message = f"JD emphasizes '{term}' (distinctive term in the Required section); nothing on your resume currently reflects this."
            suggestions.append({"type": "true_gap", "jd_term": term, "resume_key": None, "message": message})

    return suggestions
