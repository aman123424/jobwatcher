"""
fitmodel/features/engineered_features.py
===========================================

Adapter over backend/scoring's hard-filter GATES and per-tier skill-
match counts - deliberately NOT the regex scorer's own final weighted
score (see pipeline.py's own docstring for why that's excluded: it
would let the ML model just re-encode the thing it's meant to be
compared against). What's reused here is EXTRACTION logic - facts
about the JD (which gate fired, how many required-vs-preferred skills
matched) - not the regex's own opinion of how those facts should
combine into one number.

_apply_hard_filters() is called with pct=100 (a neutral input) purely
to read back WHICH gate fired, not to use the returned capped value.
"""

from ._backend_path import ensure_backend_on_path

ensure_backend_on_path()

from scoring.hard_filters import _apply_hard_filters  # noqa: E402
from scoring.jd_importance import (  # noqa: E402
    JD_IMPORTANCE_PREFERRED,
    JD_IMPORTANCE_REQUIRED,
    _best_jd_importance_for_keyword,
    _is_short_unstructured_jd,
    _jd_section_boundaries,
)
from scoring.resume_data import RESUME_SKILLS, _KEYWORD_PATTERNS  # noqa: E402

# Every atomic gate name _apply_hard_filters() can return (possibly
# joined with "_and_" for the soft-discount combinations) - see
# scorer.py's _GATE_CAVEAT_TEXT for the authoritative list this must
# stay in sync with.
_GATE_FLAG_NAMES = [
    "years", "degree", "title", "competing_stack", "internship",
    "bare_senior", "competing_framework", "moderate_years_gap",
]


def gate_flags(haystack: str) -> dict[str, int]:
    _, gate_fired = _apply_hard_filters(haystack, title="", pct=100)
    fired = set(gate_fired.split("_and_")) if gate_fired else set()
    return {f"gate_{name}": int(name in fired) for name in _GATE_FLAG_NAMES}


def skill_tier_counts(haystack: str) -> dict[str, int]:
    boundaries = _jd_section_boundaries(haystack)
    short_unstructured = _is_short_unstructured_jd(haystack, boundaries)

    counts = {"required_tier_skill_count": 0, "preferred_tier_skill_count": 0, "unclassified_tier_skill_count": 0}
    for keyword in RESUME_SKILLS:
        if not _KEYWORD_PATTERNS[keyword].search(haystack):
            continue
        importance = _best_jd_importance_for_keyword(keyword, haystack, boundaries, short_unstructured)
        if importance == JD_IMPORTANCE_REQUIRED:
            counts["required_tier_skill_count"] += 1
        elif importance == JD_IMPORTANCE_PREFERRED:
            counts["preferred_tier_skill_count"] += 1
        else:
            counts["unclassified_tier_skill_count"] += 1
    return counts
