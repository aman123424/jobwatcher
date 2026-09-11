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

DRAFT BULLETS - added alongside the message for "unverified" and
"wording_mismatch" suggestions (never for "true_gap" - there is no
real resume content to build from, and fabricating one would be
actively harmful, not just unhelpful, for a job application). These
are TEMPLATE-FILLED, not generated: an existing resume bullet with the
JD's term mechanically appended. Read them as a starting point to
hand-edit, not finished prose - said explicitly here and in the UI
copy that surfaces `draft_bullet`, not left implied.

WHY BM25 (LEXICAL), NOT EMBEDDINGS, PICKS THE DRAFT SOURCE - CONFIRMED
REAL BUG, found via two rounds of manual spot-check: embedding cosine
similarity between a short JD TERM and a full resume SENTENCE doesn't
reliably separate genuine matches from spurious ones at this
granularity - measured live, "kubernetes" (a real gap - no resume
bullet is about infra work) scored HIGHER (0.317) against the wrong
bullet ("Managed Google Workspace infrastructure...") than "rest api"
(a real, good match) scored (0.246) against the right one. No single
cosine threshold can separate these, since the bad match outscores the
good one. BM25 doesn't have this problem here: it scored the wrong
"kubernetes"/Google-Workspace pairing at exactly 0.0 (no literal token
overlap at all) and the right "unit test"/NUnit-Moq pairing at 2.07 -
a real, defensible textual basis is either there or it isn't. So
drafting requires BM25 > 0 (a literal, checkable reason the source
bullet was picked), while embeddings stay in use for detecting whether
a wording MISMATCH exists at all (a looser, exploratory question -
"is anything on the resume even in the neighborhood of this JD term"
- where a fuzzy semantic signal is actually the right tool).
"""

from features import bm25_features, embedding_features
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


# CONFIRMED REAL BUG, found via manual spot-check: drafting straight
# off the FULL chunk list picked the "skills" section's own comma-
# separated tech list as the "closest" match (trivially - it's often
# the one chunk that literally names the term), producing a nonsense
# draft like appending "explicitly using kubernetes" onto a skills
# list rather than a real accomplishment sentence. Drafting
# specifically excludes "skills"-section chunks - fine as a citation
# ("closest existing mention") elsewhere, useless as a bullet to build
# on.
def _bullet_style_chunks(resume_chunks: list[dict]) -> list[dict]:
    return [c for c in resume_chunks if c.get("section") != "skills"]


def _best_lexical_chunk(term: str, bm25_index: bm25_features.ResumeBM25Index | None) -> str | None:
    if bm25_index is None:
        return None
    scores = bm25_index.scores_for(term)
    if not scores:
        return None
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    if scores[best_idx] <= 0:
        return None  # no literal token overlap at all - nothing defensible to build a draft on
    return bm25_index.chunks[best_idx]["text"]


def _draft_unverified_bullet(term: str, source_text: str | None) -> str | None:
    if not source_text:
        return None
    return f"{source_text.rstrip('.')} — explicitly using {term}."


def _draft_wording_bullet(term: str, source_text: str | None) -> str | None:
    # Deliberately no fallback to the detection-step's own "closest"
    # chunk (which can legitimately BE the skills-list line - that's
    # fine as a citation in the message, not as a draft source) - if
    # nothing in the bullet-only set has real lexical overlap, None is
    # the honest answer, same reasoning as _draft_unverified_bullet.
    if not source_text:
        return None
    return f"{source_text.rstrip('.')} (also referred to as {term})."


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
    bullet_chunks = _bullet_style_chunks(resume_chunks)
    bullet_bm25 = bm25_features.ResumeBM25Index(bullet_chunks) if bullet_chunks else None

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
            suggestions.append({
                "type": "unverified", "jd_term": term, "resume_key": keyword, "message": message,
                "draft_bullet": _draft_unverified_bullet(term, _best_lexical_chunk(term, bullet_bm25)),
            })
            continue

        term_embedding = embedding_features.embed([term])[0]
        sims = embedding_features.cosine_sims(term_embedding, index.chunk_embeddings)
        best_idx = int(sims.argmax()) if sims.size else None
        if best_idx is not None and sims[best_idx] >= SYNONYM_SIMILARITY_THRESHOLD:
            resume_wording = index.chunks[best_idx]["text"]
            message = f"JD says '{term}'; your resume describes a related concept differently ('{resume_wording}') - consider adding '{term}' as an explicit phrasing too."
            suggestions.append({
                "type": "wording_mismatch", "jd_term": term, "resume_key": None, "message": message,
                "draft_bullet": _draft_wording_bullet(term, _best_lexical_chunk(term, bullet_bm25)),
            })
        else:
            message = f"JD emphasizes '{term}' (distinctive term in the Required section); nothing on your resume currently reflects this."
            suggestions.append({
                "type": "true_gap", "jd_term": term, "resume_key": None, "message": message,
                "draft_bullet": None,
            })

    return suggestions
