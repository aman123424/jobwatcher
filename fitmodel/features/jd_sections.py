"""
fitmodel/features/jd_sections.py
==================================

Thin adapter over backend/scoring/jd_importance.py's Required/Preferred
section-boundary detection - reused directly rather than re-derived,
since that regex work was already tuned against real postings this
session. Gives bm25_features.py and embedding_features.py a
"Required-section-only" text slice to query against, alongside the
full JD - mirroring the JD_IMPORTANCE_REQUIRED weighting that's
already proven valuable in the regex scorer.
"""

from ._backend_path import ensure_backend_on_path

ensure_backend_on_path()

from scoring.jd_importance import _jd_section_boundaries  # noqa: E402
from scoring.text_cleaning import (  # noqa: E402
    _normalize_spelled_years,
    _strip_markdown_escapes,
    strip_html,
)


def clean_jd_text(raw_description: str) -> str:
    # Same pipeline scorer.py's score_job() applies before ANY regex
    # in backend/scoring touches the text - the hard-filter gates in
    # engineered_features.py rely on this exact order (lowercase THEN
    # spelled-year normalization) to behave identically to production.
    return _normalize_spelled_years(_strip_markdown_escapes(strip_html(raw_description or "")).lower())


def required_section_text(haystack: str) -> str:
    """
    Concatenates every span tagged "required" by
    _jd_section_boundaries() - a JD can have more than one such header
    (e.g. a "Basic Qualifications" section plus a later "Required
    Skills" one) - up to the next boundary of ANY kind, or the end of
    the string. Falls back to the FULL haystack when no boundaries were
    found at all, since an unstructured JD's entire text is, in effect,
    its only "requirement" signal (same reasoning as
    hard_filters.py's SHORT_UNSTRUCTURED_CHAR_THRESHOLD handling).
    """
    boundaries = _jd_section_boundaries(haystack)
    if not boundaries:
        return haystack

    spans = []
    for i, (pos, section_type) in enumerate(boundaries):
        if section_type != "required":
            continue
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(haystack)
        spans.append(haystack[pos:end])

    return " ".join(spans) if spans else haystack
