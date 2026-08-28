"""
scoring.py
==========

Takes a normalized job (from fetchers.py) and produces a 0-100 "match
score" against Aman's resume, plus a short human-readable reason.

REWRITTEN 2026-08-28 - WHY, AND WHAT CHANGED:
The original version of this file (a flat weighted-keyword-overlap
scorer, normalized against the sum of every weight in the whole
skill list) badly under-scored real matches. A concrete case that
exposed it: a real Microsoft posting Aman found and judged a decent
fit scored 19/100 here, but 60/100 when Aman fed the same job
description to Claude directly and asked it to reason about the
match. Comparing the two approaches (see the conversation this was
built in for the full back-and-forth) turned up three real problems,
all fixed below:

  1. NORMALIZING AGAINST THE WHOLE RESUME WAS UNREALISTIC. No real
     posting mentions 20+ of Aman's specific skills - dividing by the
     sum of ALL of them meant even 2 strong, core-stack matches
     (e.g. C# + C++ on that Microsoft job) scored close to 0. Fixed
     by normalizing against a calibrated "what does a strong match
     actually look like" reference score instead (see
     STRONG_MATCH_REFERENCE_SCORE below).
  2. EVERY SKILL COUNTED THE SAME REGARDLESS OF HOW SOLID THE
     EVIDENCE FOR IT IS. Claude's manual reasoning explicitly
     distinguished skills backed by a real resume bullet ("evidence")
     from skills that just sit in the Technical Skills list with
     nothing demonstrating them ("unverified claim") - and weighted
     the first kind more. Fixed by classifying every skill into
     EVIDENTIAL_SKILLS or not, and applying a confidence multiplier
     based on that (see RESUME_CONFIDENCE_* below).
  3. EVERY SKILL COUNTED THE SAME REGARDLESS OF HOW IMPORTANT IT IS
     IN *THIS SPECIFIC POSTING*. A skill listed under a job's
     "Required Qualifications" header means something different from
     the same skill appearing once in a throwaway sentence. Fixed by
     detecting "Required" vs "Preferred" section headers in the job
     description text and weighting matches found in each
     differently (see JD_IMPORTANCE_* and _jd_section_boundaries()
     below) - though this only works where we actually have real
     description text with structure to detect in the first place;
     see the WORKDAY LIMITATION note further down for where this
     breaks down completely.

Also added, separately: simple regex-based HARD FILTERS for
years-of-experience and degree requirements (see _apply_hard_filters()
below) - matching how Claude's manual reasoning treated "5+ years
required, no equivalent-experience clause" as an almost-automatic
low score regardless of how good the rest of the match looked.

STILL HONEST ABOUT WHAT THIS IS NOT: this is still pattern-matching,
not semantic understanding. It cannot tell that "kernel debugging"
and "business workflow automation" are different KINDS of engineering
work even when both technically involve C++ - that's real-language
judgment, deliberately left for a later LLM-based stage, not
attempted here. What changed today makes the pattern-matching itself
more accurate; it doesn't add reasoning it didn't have before.

WORKDAY LIMITATION - READ THIS BEFORE TRUSTING WORKDAY SCORES: 20 of
the companies in companies.py are on Workday, and fetch_workday's own
docstring (see fetchers.py) already documents that Workday's list API
gives NO real job description at all - raw_description is just the
job's own title, repeated. That means for every Workday job:
  - The keyword-overlap check above has only the TITLE to search,
    not real description text - most skills will never match at all,
    however good the actual fit is, simply because they're never
    given the chance to appear anywhere.
  - The new JD-importance detection in this rewrite (point 3 above)
    can NEVER find anything - there's no "Required Qualifications"
    section to detect in a title-only string, so every Workday match
    falls back to JD_IMPORTANCE_UNCLASSIFIED (the lowest tier) by
    definition, every time, for every skill, on every one of those 20
    companies.
  - The hard filters below (years/degree) also can't find anything -
    "5+ years" and "or equivalent experience" clauses live in the
    body of a real posting, which Workday never gives us.
This isn't something today's rewrite can fix - it needs Workday's
own JOB DETAIL endpoint (one extra request PER JOB, the same
tradeoff already declined for SmartRecruiters - see that function's
docstring in fetchers.py) to even have real text to work with. Until
that's built, treat every Workday-sourced match_score as scored on
title-only information - meaningfully less trustworthy than a score
from Greenhouse, Lever, Ashby, DE Shaw, or pcsx, which all give real
description text.
"""

import re

# =============================================================================
# RESUME DATA
# =============================================================================
# Every skill below comes from Aman's actual resume (Aman_Kulwal_Resume.pdf,
# read 2026-08-27) - either the Technical Skills section, or named directly
# inside an Experience/Projects/Leadership bullet. Two skills used to live
# here without appearing ANYWHERE on the current resume (python, and the
# separate "design patterns" entry that wasn't the resume's actual wording)
# - both removed in this rewrite rather than silently kept as stale data;
# "agile"/"scrum" (also not on the current resume) were left in at their
# original low weight since removing them changes almost nothing either way.

# Base weight (1-5): how central this skill is to Aman's real profile,
# INDEPENDENT of whether any one job posting treats it as important -
# that's JD_IMPORTANCE, calculated per-job further down, not baked in here.
RESUME_SKILLS = {
    "c#": 5, ".net": 5, "typescript": 4, "react": 4, "javascript": 4, "selenium": 4,
    "typegraphql": 3, "typeorm": 3, "flutter": 3, "graphql": 3,
    "nunit": 3, "moq": 3, "postgresql": 3, "redux": 3, "dsa": 3,
    "system design": 3, "winforms": 3, "sql": 3, "c++": 3, "node.js": 3, "nodejs": 3,
    "solid principles": 2, "oop": 2, "tdd": 2, "ci/cd": 2,
    "unit test": 2, "integration test": 2, "github": 2, "copilot": 2,
    "html": 2, "css": 2, "docker": 2, "kubernetes": 2, "aws": 2,
    "rest api": 2, "git": 2, "gitlab": 2, "azure devops": 2,
    "spire.pdf": 2, "google oauth": 2, "dart": 2,
    "visual studio": 1, "vs code": 1, "digitalocean": 1, "agile": 1, "scrum": 1,
}

# WHICH skills above are EVIDENTIAL (get full confidence, see
# RESUME_CONFIDENCE_EVIDENTIAL below) vs left as UNVERIFIED (get half
# confidence, by ELIMINATION - anything in RESUME_SKILLS but not listed
# here). A skill ends up evidential because:
#   (a) it's named directly inside a real bullet describing work Aman
#       actually did (e.g. "c#" - "using C#, .NET" at WiseTech Global)
EVIDENTIAL_SKILLS = {
    # (a) named directly in a resume bullet
    "c#", ".net", "typescript", "react", "selenium", "typegraphql",
    "typeorm", "flutter", "graphql", "nunit", "moq", "postgresql",
    "redux", "spire.pdf", "google oauth", "system design", "ci/cd",
    "unit test", "integration test", "tdd", "github", "copilot", "dsa", "solid principles", "oop",
    "html", "css", "javascript",
}

RESUME_CONFIDENCE_EVIDENTIAL = 1.0
RESUME_CONFIDENCE_UNVERIFIED = 0.5


def _compile_keyword_pattern(keyword: str) -> re.Pattern:
    """
    Builds a regex that finds `keyword` only as a genuinely standalone
    match, not as a fragment buried inside a longer, unrelated word.
    THIS MATTERS: plain substring checking (the original approach) is
    what let "aws" match inside "...applicable local laws..." on a
    real job description, silently inflating that job's score with a
    skill that was never actually mentioned - confirmed live on
    2026-08-28. Short keywords are the ones most at risk this way:
    "git" inside "digital"/"legitimate", "oop" inside "cooperate", etc.

    `(?<![a-z0-9])` and `(?![a-z0-9])` are "lookaround" patterns - they
    check what's immediately before/after the match WITHOUT actually
    consuming those characters as part of the match itself. Together
    they mean "the character right before this match, and the
    character right after it, must NOT be a letter or digit" (start-
    of-text and end-of-text also satisfy this, since there's no
    character there at all to fail the check). That's what correctly
    rejects "aws" inside "laws" (the letter before it, 'l', fails the
    lookbehind) while still matching a real standalone "AWS" (preceded
    and followed by a space, punctuation, or the edge of the text).

    This works even for keywords containing punctuation (c#, .net,
    c++, spire.pdf) without any special-casing, because re.escape()
    below treats every character of the keyword literally, and
    punctuation characters like '#'/'+'/'.' already fail the
    [a-z0-9] check on their own - there's nothing extra to handle.
    """
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])")


# Every keyword's pattern built ONCE here rather than re-compiling the
# same regex on every single score_job() call - regex compilation has
# real (if small) cost, and this dict never changes at runtime.
_KEYWORD_PATTERNS = {keyword: _compile_keyword_pattern(keyword) for keyword in RESUME_SKILLS}


def _resume_confidence(keyword: str) -> float:
    """How much to trust a match on this keyword, based on how solid
    the evidence for it is on Aman's own resume (see EVIDENTIAL_SKILLS
    above for the two ways a skill earns full confidence)."""
    return RESUME_CONFIDENCE_EVIDENTIAL if keyword in EVIDENTIAL_SKILLS else RESUME_CONFIDENCE_UNVERIFIED


# Short, plain-English explanation of WHERE each keyword comes from in
# my actual background. Used to build the match_reason string, so
# the output says something like "2 years hands-on C#/.NET at WiseTech
# Global" instead of just repeating the bare keyword "c#".
RESUME_CONTEXT = {
    "c#": "2 years hands-on C#/.NET at WiseTech Global (AE Customs, UAE Manifest workflows)",
    ".net": "2 years hands-on .NET at WiseTech Global",
    "typescript": "TypeScript (React TS) across the HAS Complaints Portal and Shaastra registration platform",
    "react": "React across Desklamp internship, HAS Complaints Portal, and Shaastra registration platform",
    "javascript": "JavaScript underlying all React/web project work - confirmed strong skill",
    "selenium": "Selenium-based tariff/exchange-rate data ingestion pipeline built at WiseTech Global",
    "typegraphql": "TypeGraphQL - HAS Complaints Portal backend",
    "typeorm": "TypeORM - HAS Complaints Portal backend",
    "flutter": "Flutter (InstiSpace app, 11k+ users)",
    "graphql": "GraphQL - InstiSpace app (graphql_flutter) and TypeGraphQL in the HAS Portal",
    "nunit": "NUnit - authored 500+ tests at WiseTech, built the NUnitCore-to-NUnit4 migration tool",
    "moq": "Moq - authored 500+ unit/integration tests at WiseTech Global",
    "postgresql": "PostgreSQL - HAS Complaints Portal",
    "redux": "Redux for state management on the Shaastra registration platform (15k+ registrations)",
    "spire.pdf": "Spire.PDF - tariff/exchange-rate data ingestion pipeline at WiseTech",
    "google oauth": "Google OAuth - one-click signup on the HAS Complaints Portal",
    "system design": "System design - architected the HAS Portal's 3-tier RBAC hierarchy",
    "ci/cd": "CI/CD pipeline safeguarded via 500+ authored tests at WiseTech Global",
    "unit test": "500+ unit tests authored at WiseTech Global",
    "integration test": "500+ integration tests authored at WiseTech Global",
    "tdd": "TDD - confirmed strong skill",
    "github": "GitHub - confirmed strong skill",
    "copilot": "GitHub Copilot - confirmed strong skill",
    "dsa": "DSA - confirmed strong skill, IIT Madras background",
    "solid principles": "SOLID Principles - confirmed strong skill",
    "oop": "OOP - confirmed strong skill",
    "html": "HTML - confirmed strong skill",
    "css": "CSS - confirmed strong skill",
    "c++": "C++ - listed skill (DSA/IIT Madras background), not resume-bullet-evidenced",
    "sql": "SQL - listed skill (used implicitly via PostgreSQL work), not resume-bullet-evidenced",
    "dart": "Dart - listed skill underlying Flutter work, not resume-bullet-evidenced",
    "node.js": "Node.js - listed skill, not resume-bullet-evidenced",
    "nodejs": "Node.js - listed skill, not resume-bullet-evidenced",
    "winforms": "WinForms - listed skill, not resume-bullet-evidenced",
    "docker": "Docker - listed skill, not resume-bullet-evidenced",
    "kubernetes": "Kubernetes - listed skill, not resume-bullet-evidenced",
    "aws": "AWS - listed skill, not resume-bullet-evidenced",
    "rest api": "REST APIs - listed skill, not resume-bullet-evidenced",
    "git": "Git - listed skill, not resume-bullet-evidenced",
    "gitlab": "GitLab - listed skill, not resume-bullet-evidenced",
    "visual studio": "Visual Studio - listed skill, not resume-bullet-evidenced",
    "vs code": "VS Code - listed skill, not resume-bullet-evidenced",
    "azure devops": "Azure DevOps - listed skill, not resume-bullet-evidenced",
    "digitalocean": "DigitalOcean - listed skill, not resume-bullet-evidenced",
}

# =============================================================================
# JD (job description) IMPORTANCE DETECTION
# =============================================================================
# Header phrases that mark the start of a "this is required" section in a
# real job description. Matched case-insensitively; deliberately a mix of
# the most common real phrasings seen across postings so far.
_REQUIRED_SECTION_RE = re.compile(
    r"(required qualifications|must[\s-]have|basic qualifications|"
    r"minimum qualifications|requirements\s*:|what you.?ll need|you have)",
    re.IGNORECASE,
)
# Same idea, for "this is nice but optional" sections.
_PREFERRED_SECTION_RE = re.compile(
    r"(preferred qualifications|nice[\s-]to[\s-]have|bonus\s+(points|if)|"
    r"good to have|preferred skills|desired skills|pluses)",
    re.IGNORECASE,
)

# How much a matched skill counts depending on which section (if any) it
# was found under. These are MULTIPLIERS applied to base_weight *
# resume_confidence - see score_job() below for how they combine.
JD_IMPORTANCE_REQUIRED = 1.5
JD_IMPORTANCE_PREFERRED = 1.0
JD_IMPORTANCE_UNCLASSIFIED = 0.6


def _jd_section_boundaries(haystack: str) -> list[tuple[int, str]]:
    """
    Scans the full job text for every "Required"/"Preferred" section
    header and returns their positions, sorted left-to-right, e.g.
    [(120, "required"), (540, "preferred")] means a "Required" section
    starts at character 120 and a "Preferred" section starts at
    character 540. Anything BEFORE the first entry in this list (or
    every position, if the list is empty - no headers found at all,
    which is the normal case for Workday/SmartRecruiters' thin
    descriptions) is "unclassified" - see _jd_importance_at() below.
    """
    boundaries = [(m.start(), "required") for m in _REQUIRED_SECTION_RE.finditer(haystack)]
    boundaries += [(m.start(), "preferred") for m in _PREFERRED_SECTION_RE.finditer(haystack)]
    boundaries.sort(key=lambda b: b[0])
    return boundaries


def _jd_importance_at(position: int, boundaries: list[tuple[int, str]]) -> float:
    """
    Given a character position in the job text (where a resume keyword
    was found) and the section boundaries from _jd_section_boundaries()
    above, returns which importance tier that position falls under -
    whichever section header most recently appeared BEFORE this
    position, or "unclassified" if none has yet (or none exist at all).
    """
    current_section = None
    for boundary_pos, section_type in boundaries:
        if boundary_pos > position:
            break
        current_section = section_type
    if current_section == "required":
        return JD_IMPORTANCE_REQUIRED
    if current_section == "preferred":
        return JD_IMPORTANCE_PREFERRED
    return JD_IMPORTANCE_UNCLASSIFIED


def _best_jd_importance_for_keyword(keyword: str, haystack: str, boundaries: list[tuple[int, str]]) -> float:
    """
    A skill can be mentioned more than once in the same posting (once
    in an overview paragraph, again under "Required") - this takes the
    HIGHEST importance tier found across every occurrence, rather than
    just the first one, so a skill genuinely gets credit for being
    required even if it's ALSO casually mentioned elsewhere.

    Uses the same word-boundary-safe pattern from _KEYWORD_PATTERNS
    that score_job() below uses to decide whether a keyword matched at
    all - important to keep these consistent, otherwise a keyword could
    correctly get REJECTED as a false-positive substring match in one
    place while still being searched for (and found) the naive way here.
    """
    best = 0.0
    for m in _KEYWORD_PATTERNS[keyword].finditer(haystack):
        best = max(best, _jd_importance_at(m.start(), boundaries))
    return best

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

# =============================================================================
# HARD FILTERS (years of experience / degree requirements)
# =============================================================================
# Aman's real total professional experience, used as the baseline below.
# ~2 years, per WiseTech Global's July 2024 - May 2026 dates on his resume.
BASELINE_YEARS_EXPERIENCE = 2

# How many years ABOVE the baseline a posting can require before we treat
# it as a real mismatch (rather than just "a bit senior but plausible").
YEARS_OVER_BASELINE_TO_GATE = 3

# Matches "5+ years", "5-8 years", "2 years", etc. Deliberately simple -
# this WILL occasionally false-positive on unrelated numbers followed by
# "years" in boilerplate company-history text ("founded 10 years ago") -
# a known, accepted limitation of regex-based pattern matching, same
# spirit as _strip_html()'s own honesty about its limits below.
_YEARS_REQUIREMENT_RE = re.compile(r"(\d+)\s*(?:\+|-\s*\d+)?\s*years?", re.IGNORECASE)

# Matches a genuine "or equivalent experience"-style escape clause.
# TIGHTENED 2026-08-28 after two real false positives, confirmed live:
#   - A Twilio posting: "Degree in Computer Science... or equivalent
#     work experience" let a completely SEPARATE, unrelated "5+ years
#     of work experience" bullet earlier in the same posting escape
#     gating - the clause was about the DEGREE, not the years.
#   - A ServiceNow posting: "Kafka or equivalent streaming..." and
#     "Java, Python, Go or equivalent, used in production" both matched
#     the old bare "or equivalent" pattern despite having NOTHING to do
#     with experience at all - "or equivalent" is just common English
#     for "or a similar/comparable technology" in a skills list.
# Fixed two ways: (1) "experience" must now actually appear within a
# couple of words of "equivalent" - neither Kafka/Java example above
# has that word anywhere nearby, so they no longer match at all. (2)
# even a genuine "...experience" match only cancels a NEARBY gate, not
# every gate in the whole document - see _apply_hard_filters() below.
_EQUIVALENT_EXPERIENCE_RE = re.compile(r"or\s+equivalent(\s+\w+){0,2}\s+experience", re.IGNORECASE)

# Matches "Master's [degree] required" / "PhD required" - Bachelor's-level
# requirements are NOT gated here, since Aman already has one.
_DEGREE_REQUIRED_RE = re.compile(r"(master.?s|ph\.?d\.?)\s+(degree\s+)?(is\s+)?required", re.IGNORECASE)

# When a hard filter fires (a real gap with no escape clause), the score
# gets CAPPED at this ceiling, not just discounted - mirroring how
# Claude's manual reasoning treated this as "near-automatic low score,
# regardless of how good the rest looked."
HARD_GATE_SCORE_CEILING = 30

# How close (in characters) a genuine escape clause needs to be to the
# SPECIFIC years/degree requirement it's meant to excuse, to count as
# applying to it. Without this, a posting with a valid escape clause
# for its degree requirement (like Twilio's) would incorrectly excuse
# an entirely separate, unrelated years requirement stated elsewhere in
# the same posting - a real bug found and fixed alongside this file.
ESCAPE_CLAUSE_PROXIMITY_CHARS = 200


def _apply_hard_filters(haystack: str, title: str, pct: int) -> tuple[int, bool]:
    """
    Checks for a years-of-experience or degree requirement Aman clearly
    doesn't meet, WITH no "or equivalent experience" escape clause found
    NEAR that specific requirement (not just anywhere in the whole
    document - see ESCAPE_CLAUSE_PROXIMITY_CHARS above for why that
    distinction matters). If found, caps pct at HARD_GATE_SCORE_CEILING
    regardless of how high the keyword-overlap score was. Returns
    (possibly-capped pct, whether a gate actually fired) - the second
    value lets _build_reason() below mention it in match_reason.

    ALSO gates on a senior title word (SENIOR_TITLE_WORDS - "staff",
    "principal", "lead", ...) - added 2026-08-28 after a real posting
    titled "Senior/Staff Applied Research Software Engineer" scored 97.
    Its body text never stated a number of years at all (so the
    years-regex above had nothing to catch), but the TITLE alone is
    already trusted as a strong, low-noise seniority signal elsewhere
    in this file (see SENIOR_TITLE_WORDS's own comment) - it just
    wasn't being used to affect match_score, only added as caveat TEXT
    in _build_reason() below, with the number itself left untouched.
    No escape-clause check for this one: a job's own title calling
    itself "Staff" isn't something a body-text "or equivalent
    experience" clause elsewhere would plausibly override.
    """
    escape_positions = [m.start() for m in _EQUIVALENT_EXPERIENCE_RE.finditer(haystack)]

    def has_nearby_escape(position: int) -> bool:
        return any(abs(position - escape_pos) <= ESCAPE_CLAUSE_PROXIMITY_CHARS for escape_pos in escape_positions)

    years_gate = False
    for m in _YEARS_REQUIREMENT_RE.finditer(haystack):
        years = int(m.group(1))
        if years >= BASELINE_YEARS_EXPERIENCE + YEARS_OVER_BASELINE_TO_GATE and not has_nearby_escape(m.start()):
            years_gate = True
            break

    degree_match = _DEGREE_REQUIRED_RE.search(haystack)
    degree_gate = bool(degree_match) and not has_nearby_escape(degree_match.start())

    title_lower = title.lower()
    title_gate = any(w in title_lower for w in SENIOR_TITLE_WORDS)

    if years_gate or degree_gate or title_gate:
        return min(pct, HARD_GATE_SCORE_CEILING), True
    return pct, False


# Words in a job TITLE that suggest a seniority level well above
# Aman's current ~2 years. This is a separate, simpler check from the
# keyword scorer above — title-based, not description-based, because
# seniority words in a title are a strong, low-noise signal ("Staff
# Software Engineer" almost always IS a Staff-level role), whereas the
# same words buried in a long description are much noisier.
SENIOR_TITLE_WORDS = ["staff", "principal", "director", "head of", "vp",
                      "vice president", "lead", "architect"]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """
    Greenhouse's job descriptions come back as HTML (e.g.
    "<p>We are looking for...</p>"). This is a deliberately simple
    regex-based tag stripper — good enough for keyword matching, where
    we only care about the visible words, not proper HTML parsing.
    A production system handling untrusted HTML more seriously would
    use a real parser (e.g. BeautifulSoup) instead of a regex, since
    regexes are not a reliable way to parse arbitrary HTML in general
    — but for "strip tags before keyword-matching," this is fine.
    """
    return _HTML_TAG_RE.sub(" ", text or "")


def score_job(job: dict) -> dict:
    """
    Takes one normalized job dict (from fetchers.py) and returns it
    with three new keys added: match_score, match_reason, seniority.

    We MODIFY AND RETURN the same dict (rather than a separate scores
    list) so that downstream code (state.py, main.py) only ever has to
    pass one object per job around, not two things that have to stay
    in sync with each other.

    See this file's module docstring for the full "why" behind the
    formula below - in short: for every resume skill found in the job
    text, its contribution is base_weight x resume_confidence (how
    solid the evidence for Aman actually having that skill is) x
    jd_importance (how important THIS posting treats that skill -
    Required section, Preferred section, or just mentioned).
    """
    title = job.get("title", "") or ""
    description = _strip_html(job.get("raw_description", ""))
    haystack = f"{title} {description}".lower()

    boundaries = _jd_section_boundaries(haystack)

    matched_keywords = []
    raw_score = 0.0
    for keyword, base_weight in RESUME_SKILLS.items():
        # Word-boundary-safe search (see _compile_keyword_pattern's
        # docstring above) rather than a plain `keyword in haystack`
        # substring check - that naive version is what let "aws" match
        # inside "...applicable local laws..." on a real job description.
        if not _KEYWORD_PATTERNS[keyword].search(haystack):
            continue
        matched_keywords.append(keyword)
        jd_importance = _best_jd_importance_for_keyword(keyword, haystack, boundaries)
        raw_score += base_weight * _resume_confidence(keyword) * jd_importance

    pct = round(min((raw_score / STRONG_MATCH_REFERENCE_SCORE) * 100, 97))
    pct, hard_gated = _apply_hard_filters(haystack, title, pct)

    job["match_score"] = pct
    job["match_reason"] = _build_reason(title, matched_keywords, pct, hard_gated)
    job["seniority"] = _infer_seniority(title)
    return job


def _build_reason(title: str, matched_keywords: list[str], score: int, hard_gated: bool) -> str:
    title_lower = title.lower()

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
    if any(w in title_lower for w in SENIOR_TITLE_WORDS):
        caveats.append("title suggests more YOE than Aman's ~2 years")
    if "intern" in title_lower:
        caveats.append("internship level")
    if hard_gated:
        caveats.append("capped: posting requires more experience/education than Aman has, with no 'or equivalent' clause found")

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
# every other regex-based check in this file being upfront about its
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
