"""
scoring/scorer.py
===================

The actual entry point other files call: score_job() takes one
normalized job dict (from the fetchers package) and returns it with
match_score/match_reason/seniority added, plus the small handful of
resume-independent job filters (is_relevant_title, is_india_location,
is_recently_posted) main.py and ingest.py apply before scoring ever
runs. See this package's own __init__.py docstring for the full
"why this formula" rewrite history and the Workday-limitation caveat.
"""

from datetime import datetime, timedelta, timezone

from job_dates import parse_posted_datetime

from .hard_filters import SENIOR_TITLE_WORDS, _apply_hard_filters
from .jd_importance import (
    _best_jd_importance_for_keyword,
    _is_short_unstructured_jd,
    _jd_section_boundaries,
)
from .resume_data import RESUME_CONTEXT, RESUME_SKILLS, _KEYWORD_PATTERNS, _resume_confidence
from .text_cleaning import _normalize_spelled_years, _strip_markdown_escapes, strip_html

# =============================================================================
# NORMALIZATION
# =============================================================================
# The reference "what does a strong match look like" score that raw_score
# below gets divided by to produce a 0-100 percentage. Roughly calibrated
# as "2-3 core, evidential skills matched under a Required section" -
# e.g. C# (5) + TypeScript (4), both evidential (x1.0) and required
# (x1.5): (5 + 4) * 1.0 * 1.5 = 13.5, so a genuinely strong multi-skill
# match should comfortably clear 100%+ (capped below) with real skills.
# THIS IS A HEURISTIC, NOT A DERIVED CONSTANT - same as the old *1.8
# multiplier it replaces, expect to adjust this number once real live
# scores are visible across a range of actual postings.
STRONG_MATCH_REFERENCE_SCORE = 15

# CONFIRMED REAL BUG, found 2026-09-06 testing against 123 real postings
# from our own 47 target companies: Microsoft/Amazon/etc routinely phrase
# their core language requirement as ONE OR-list of interchangeable
# options - e.g. a real Microsoft posting's entire required qualification
# was "4+ years technical engineering experience with coding in languages
# including, but not limited to, C, C++, C#, Java, JavaScript, or
# Python." Aman happens to know several of those (C#/.NET, Python,
# JavaScript, C++) - the OLD code matched each one as its own independent
# keyword and SUMMED all four contributions at full REQUIRED weight, as
# if the posting had asked for all four separately, scoring this 97/100
# (LLM, correctly reading it as "any ONE of these, pick one": 20/100,
# capped mainly by the 4-year floor and a specialized DRM domain the
# language match says nothing about). A posting naming a genuine
# multi-language REQUIREMENT (e.g. "Python backend, JavaScript frontend"
# as two separate bullets far apart in the doc) is a different, rarer
# shape - this only collapses matches that are proximate enough to
# plausibly be the SAME enumerated list, same spirit as
# COMPETING_STACK_PROXIMITY_CHARS elsewhere in this package.
LANGUAGE_GROUP_KEYWORDS = {"c#/.net", "python", "javascript", "typescript", "c++"}
LANGUAGE_GROUP_PROXIMITY_CHARS = 100


def _collapse_language_or_lists(contributions: dict[str, float], haystack: str) -> None:
    """
    Mutates `contributions` in place: when two or more LANGUAGE_GROUP
    keywords first appear within LANGUAGE_GROUP_PROXIMITY_CHARS of each
    other (almost always the same "one of X, Y, or Z" enumerated
    requirement, not independent asks), keeps only the highest-
    contributing one from that cluster and zeroes the rest - they stay
    out of matched_keywords/match_reason too, same as never having
    matched, since crediting them separately would double (or
    quadruple-) count one single requirement.
    """
    positions = []
    for kw in LANGUAGE_GROUP_KEYWORDS:
        if kw not in contributions:
            continue
        m = _KEYWORD_PATTERNS[kw].search(haystack)
        if m:
            positions.append((m.start(), kw))
    positions.sort()

    cluster = []
    for pos, kw in positions:
        if cluster and pos - cluster[-1][0] > LANGUAGE_GROUP_PROXIMITY_CHARS:
            _keep_best_and_zero_rest(cluster, contributions)
            cluster = []
        cluster.append((pos, kw))
    if cluster:
        _keep_best_and_zero_rest(cluster, contributions)


def _keep_best_and_zero_rest(cluster: list[tuple[int, str]], contributions: dict[str, float]) -> None:
    if len(cluster) < 2:
        return
    best_kw = max((kw for _, kw in cluster), key=lambda kw: contributions[kw])
    for _, kw in cluster:
        if kw != best_kw:
            contributions[kw] = 0.0


def score_job(job: dict) -> dict:
    """
    Takes one normalized job dict (from the fetchers package) and
    returns it with three new keys added: match_score, match_reason,
    seniority.

    We MODIFY AND RETURN the same dict (rather than a separate scores
    list) so that downstream code (state.py, main.py) only ever has to
    pass one object per job around, not two things that have to stay
    in sync with each other.

    See this package's own __init__.py docstring for the full "why"
    behind the formula below - in short: for every resume skill found
    in the job text, its contribution is base_weight x
    resume_confidence (how solid the evidence for Aman actually having
    that skill is) x jd_importance (how important THIS posting treats
    that skill - Required section, Preferred section, or just mentioned).
    """
    title = _strip_markdown_escapes(job.get("title", "") or "")
    description = _strip_markdown_escapes(strip_html(job.get("raw_description", "")))
    haystack = _normalize_spelled_years(f"{title} {description}".lower())

    boundaries = _jd_section_boundaries(haystack)
    short_unstructured = _is_short_unstructured_jd(haystack, boundaries)

    contributions = {}
    for keyword, base_weight in RESUME_SKILLS.items():
        # Word-boundary-safe search (see resume_data.py's
        # _compile_keyword_pattern docstring) rather than a plain
        # `keyword in haystack` substring check - that naive version is
        # what let "aws" match inside "...applicable local laws..." on
        # a real job description.
        if not _KEYWORD_PATTERNS[keyword].search(haystack):
            continue
        jd_importance = _best_jd_importance_for_keyword(keyword, haystack, boundaries, short_unstructured)
        contributions[keyword] = base_weight * _resume_confidence(keyword) * jd_importance

    _collapse_language_or_lists(contributions, haystack)
    matched_keywords = [kw for kw, contribution in contributions.items() if contribution > 0]
    raw_score = sum(contributions.values())

    pct = round(min((raw_score / STRONG_MATCH_REFERENCE_SCORE) * 100, 97))
    pct, gate_fired = _apply_hard_filters(haystack, title, pct)

    job["match_score"] = pct
    job["match_reason"] = _build_reason(matched_keywords, pct, gate_fired)
    job["seniority"] = _infer_seniority(title)
    return job


# What each ATOMIC gate reads as in match_reason - kept as a lookup
# table rather than an if/elif chain in _build_reason() below, since
# it's pure data (gate name -> caveat sentence), not branching logic.
# hard_filters._apply_hard_filters() can return more than one of these
# joined with "_and_" (e.g. "bare_senior_and_moderate_years_gap") when
# multiple soft discounts fire together - _build_reason() below splits
# on that separator and looks each part up individually, rather than
# this dict needing an entry for every combination by hand (added
# 2026-09-06 once a third soft discount - moderate_years_gap - made the
# old one-entry-per-combination approach start multiplying combinations
# it couldn't keep up with).
_GATE_CAVEAT_TEXT = {
    "years": "capped: posting requires more years of experience than Aman has, with no 'or equivalent' clause found",
    "degree": "capped: posting requires a degree tier (Master's/PhD) Aman doesn't have, with no 'or equivalent' clause found",
    "title": "capped: title implies a seniority level (Staff/Principal/Director/Lead/...) well above Aman's ~2 years",
    "bare_senior": "discounted: 'Senior'/'Sr' title implies more YOE than Aman's ~2 years",
    "competing_stack": "capped: posting is built around a stack (Java/Spring Boot/Golang/COBOL/Salesforce Apex/native iOS/PHP/Rust) Aman has no real experience in",
    "competing_framework": "discounted: right language (Python), but requires Django specifically - Aman's Python experience is FastAPI, not Django",
    "moderate_years_gap": "discounted: posting requires 1-2 years more experience than Aman has - not a hard mismatch, but a real gap",
    "internship": "capped: title is an internship/trainee role, a level below Aman's ~2 years of professional experience",
}


def _build_reason(matched_keywords: list[str], score: int, gate_fired: str | None) -> str:
    if score >= 55:
        strength = "Strong match"
    elif score >= 35:
        strength = "Moderate match"
    else:
        strength = "Partial match"

    reasons = [RESUME_CONTEXT[kw] for kw in matched_keywords[:4] if kw in RESUME_CONTEXT]
    if not reasons:
        reasons.append("limited overlap with resume's core stack (C#/.NET, React, Selenium)")

    caveats = []
    if gate_fired:
        caveats.extend(_GATE_CAVEAT_TEXT[part] for part in gate_fired.split("_and_"))

    text = f"{strength}: " + "; ".join(reasons)
    if caveats:
        text += ". Caveat: " + "; ".join(caveats)
    return text


def _infer_seniority(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["intern", "trainee"]):
        return "Internship"
    if any(w in t for w in SENIOR_TITLE_WORDS):
        return "Lead/Principal"
    if "senior" in t or "sr." in t or "sr " in t:
        return "Senior"
    return "Entry/Mid-Level"


# Title keywords used to filter the full list of a company's open
# roles down to just the ones actually relevant to a Software Engineer
# search — companies post Sales, HR, Legal, etc. roles too, and we
# don't want those going through the scorer at all.
RELEVANT_TITLE_KEYWORDS = [
    "software engineer", "swe", "sde", "software development engineer",
    "backend", "frontend", "front end", "full stack", "fullstack",
    "developer", ".net developer", "application engineer",
]


def is_relevant_title(title: str) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in RELEVANT_TITLE_KEYWORDS)


# Added 2026-08-28: Aman only wants India-based postings - most of
# Tier 1/2 (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) fetch
# EVERY country's postings with no location filter at all (only the
# custom fetchers - pcsx, Amazon - filter by location at the API level
# already). This is the universal, platform-agnostic fallback: a plain
# text check on whatever each platform's own "location" field gives us.
#
# "india" alone as the only check would miss real India postings whose
# location string is just a bare city name with no country appended
# (seen on some companies' raw data) - so this also matches a list of
# major Indian tech hub cities as a fallback signal. This is a text
# heuristic, not a lookup against a real geography database - it can
# still miss a genuinely India-based role in a smaller city never
# added to this list, or (much less likely) mismatch a same-named city
# elsewhere in the world. Good enough for this purpose, same spirit as
# every other regex-based check in this package being upfront about its
# limits rather than pretending to be exact.
_INDIA_LOCATION_KEYWORDS = [
    "india",
    "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "chennai",
    "gurugram", "gurgaon", "noida", "new delhi", "delhi", "kolkata",
    "ahmedabad",
]


def is_india_location(location: str) -> bool:
    loc = (location or "").lower()
    return any(kw in loc for kw in _INDIA_LOCATION_KEYWORDS)


# Added 2026-08-29, part of the /refresh architecture change: Aman
# wants ONLY postings from the last 24 hours, applied UNIFORMLY across
# every platform - not the mix that existed before (a 2-day EFFICIENCY
# buffer on Workday/SmartRecruiters/pcsx only, meant to avoid wasted
# fetch/enrichment work on old postings state.py already knows about;
# Greenhouse/Lever/Ashby/DE Shaw had NO freshness filtering at all).
# This is a separate, stricter, product-level rule - see main.py's
# fetch_and_score_all() for where this actually gets applied to the
# final job list, once per job, regardless of platform.
REFRESH_WINDOW_HOURS = 24


def is_recently_posted(job: dict, hours: int = REFRESH_WINDOW_HOURS) -> bool:
    """
    True if `job` was posted within the last `hours` hours, using
    parse_posted_datetime() (job_dates.py) to turn whatever that
    platform's own posted-date data looks like into one comparable
    real datetime - see that function's docstring for exactly how
    precise (or not) that is per platform.

    UNKNOWN AGE PASSES THE FILTER (returns True), not fails it - DE
    Shaw has NO posted-date field at all, so parse_posted_datetime()
    always returns None for it, and there's no way to ever confirm
    a DE Shaw job is within the window. Silently dropping every DE
    Shaw posting over an unanswerable question felt worse than
    letting them through unfiltered - same "can't tell -> don't
    assume the worst" reasoning already used for Workday's own
    unrecognized postedOn labels (see workday_posted_on_days() in
    job_dates.py). Practical effect: DE Shaw's freshness is
    unverified, not guaranteed, under this filter - worth knowing
    before trusting a DE Shaw match_score the same way you'd trust
    one from a platform that gives real timestamps.
    """
    posted_at = parse_posted_datetime(job)
    if posted_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return posted_at >= cutoff
