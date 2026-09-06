"""
scoring/jd_importance.py
==========================

Detects "Required Qualifications" vs "Preferred Qualifications"
sections in a job posting's text, and how much weight a matched skill
should get depending on which one (if either) it fell under. A skill
listed under "Required" means something different from the same skill
appearing once in a throwaway sentence - see scoring/scorer.py's
own docstring for the full "why" behind this rewrite.
"""

import re

from .resume_data import _KEYWORD_PATTERNS

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
# resume_confidence - see scoring/scorer.py's score_job() for how they combine.
JD_IMPORTANCE_REQUIRED = 1.5
JD_IMPORTANCE_PREFERRED = 1.0
JD_IMPORTANCE_UNCLASSIFIED = 0.6

# CONFIRMED REAL BUG, found 2026-09-06 testing 100 real postings against
# LLM reasoning: a Zensar posting ("Your primary focus will be on
# utilizing your skills in DOTNET, Azure, and MS SQL") - 370 chars, no
# section headers anywhere - scored 26/100 here (LLM: 68) purely because
# its only two matched keywords (c#/.net, sql) fell back to the
# UNCLASSIFIED tier for lack of a "Required:" header to detect, even
# though on a posting this short there's no real skill hierarchy to
# miss - whatever IS named is the entire ask, not a throwaway mention
# buried in a wall of text. Below this length, with no headers found at
# all, treat every match as REQUIRED instead. This also fixes Workday's
# title-only postings the same way, consistent with the intent already
# documented in this package's WORKDAY LIMITATION note (see __init__.py).
SHORT_UNSTRUCTURED_CHAR_THRESHOLD = 600


def _is_short_unstructured_jd(haystack: str, boundaries: list[tuple[int, str]]) -> bool:
    return not boundaries and len(haystack) < SHORT_UNSTRUCTURED_CHAR_THRESHOLD


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


def _jd_importance_at(position: int, boundaries: list[tuple[int, str]], short_unstructured: bool = False) -> float:
    """
    Given a character position in the job text (where a resume keyword
    was found) and the section boundaries from _jd_section_boundaries()
    above, returns which importance tier that position falls under -
    whichever section header most recently appeared BEFORE this
    position, or "unclassified" if none has yet (or none exist at all) -
    except on a short, headerless posting (short_unstructured=True, see
    _is_short_unstructured_jd() above), where "unclassified" is treated
    as REQUIRED instead, since there's nothing else in the text a match
    could be a lesser mention of.
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
    if short_unstructured:
        return JD_IMPORTANCE_REQUIRED
    return JD_IMPORTANCE_UNCLASSIFIED


def _best_jd_importance_for_keyword(
    keyword: str,
    haystack: str,
    boundaries: list[tuple[int, str]],
    short_unstructured: bool = False,
) -> float:
    """
    A skill can be mentioned more than once in the same posting (once
    in an overview paragraph, again under "Required") - this takes the
    HIGHEST importance tier found across every occurrence, rather than
    just the first one, so a skill genuinely gets credit for being
    required even if it's ALSO casually mentioned elsewhere.

    Uses the same word-boundary-safe pattern from resume_data's
    _KEYWORD_PATTERNS that scorer.py's score_job() uses to decide
    whether a keyword matched at all - important to keep these
    consistent, otherwise a keyword could correctly get REJECTED as a
    false-positive substring match in one place while still being
    searched for (and found) the naive way here.
    """
    best = 0.0
    for m in _KEYWORD_PATTERNS[keyword].finditer(haystack):
        best = max(best, _jd_importance_at(m.start(), boundaries, short_unstructured))
    return best
