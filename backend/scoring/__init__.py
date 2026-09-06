"""
scoring
=======

Takes a normalized job (from the fetchers package) and produces a
0-100 "match score" against Aman's resume, plus a short human-readable
reason.

REWRITTEN 2026-08-28 - WHY, AND WHAT CHANGED:
The original version (a flat weighted-keyword-overlap scorer,
normalized against the sum of every weight in the whole skill list)
badly under-scored real matches. A concrete case that exposed it: a
real Microsoft posting Aman found and judged a decent fit scored
19/100 here, but 60/100 when Aman fed the same job description to
Claude directly and asked it to reason about the match. Comparing the
two approaches (see the conversation this was built in for the full
back-and-forth) turned up three real problems, all fixed then:

  1. NORMALIZING AGAINST THE WHOLE RESUME WAS UNREALISTIC. No real
     posting mentions 20+ of Aman's specific skills - dividing by the
     sum of ALL of them meant even 2 strong, core-stack matches
     (e.g. C# + C++ on that Microsoft job) scored close to 0. Fixed
     by normalizing against a calibrated "what does a strong match
     actually look like" reference score instead (see
     scorer.STRONG_MATCH_REFERENCE_SCORE).
  2. EVERY SKILL COUNTED THE SAME REGARDLESS OF HOW SOLID THE
     EVIDENCE FOR IT IS. Claude's manual reasoning explicitly
     distinguished skills backed by a real resume bullet ("evidence")
     from skills that just sit in the Technical Skills list with
     nothing demonstrating them ("unverified claim") - and weighted
     the first kind more. Fixed by classifying every skill into
     EVIDENTIAL_SKILLS or not (see resume_data.py), and applying a
     confidence multiplier based on that.
  3. EVERY SKILL COUNTED THE SAME REGARDLESS OF HOW IMPORTANT IT IS
     IN *THIS SPECIFIC POSTING*. A skill listed under a job's
     "Required Qualifications" header means something different from
     the same skill appearing once in a throwaway sentence. Fixed by
     detecting "Required" vs "Preferred" section headers in the job
     description text and weighting matches found in each
     differently (see jd_importance.py) - though this only works
     where we actually have real description text with structure to
     detect in the first place; see the WORKDAY LIMITATION note
     further down for where this breaks down completely.

Also added, separately: simple regex-based HARD FILTERS (see
hard_filters.py) for years-of-experience and degree requirements -
matching how Claude's manual reasoning treated "5+ years required, no
equivalent-experience clause" as an almost-automatic low score
regardless of how good the rest of the match looked. Substantially
expanded 2026-09-06 after testing against 111 real postings (22 fresh
LinkedIn/Indeed/company JDs, then 50 more via jobspy) turned up a long
list of real, confirmed bugs and gaps - see hard_filters.py's own
module docstring and each constant's comment for the specific before/
after story behind every rule in there.

STILL HONEST ABOUT WHAT THIS IS NOT: this is still pattern-matching,
not semantic understanding. It cannot tell that "kernel debugging"
and "business workflow automation" are different KINDS of engineering
work even when both technically involve C++ - that's real-language
judgment, deliberately left for a later LLM-based stage, not
attempted here. Confirmed live 2026-09-06 against real postings with
literally zero named technology (pure corporate-template boilerplate)
- these score 0 here even when a human reasoner would credit them
based on YOE fit and general role plausibility alone; no amount of
additional regex rules closes that gap, because there's nothing
specific in the text for a keyword matcher to find.

WORKDAY / SMARTRECRUITERS / PCSX (MICROSOFT) - PER-JOB ENRICHMENT, NOT
ALWAYS COMPLETE: Workday's and SmartRecruiters' LIST endpoints, and
Microsoft's pcsx search endpoint, all originally gave back only a
title (or a one-word department label) with no real description text -
the limitation this note used to describe as permanent. As of
2026-09-0x this is FIXED for all three: fetchers/workday.py's
_enrich_workday_descriptions(), fetchers/smartrecruiters.py's
_enrich_smartrecruiters_descriptions(), and fetchers/pcsx.py's
_enrich_pcsx_descriptions() each make one extra per-job DETAIL request
(only for postings that already pass is_relevant_title(), to avoid
paying that cost on jobs that were always going to get thrown away)
and overwrite raw_description with the real HTML body from that
response - the "one extra request per job" tradeoff this note used to
say was declined for SmartRecruiters is exactly what got built.
CONFIRMED via the 2026-09-06 real-data pass: a Barclays (Workday)
posting's raw_description came back as real multi-paragraph HTML, not
a repeated title.
STILL WORTH KNOWING: enrichment is a live network call per job and can
still fail (timeout, that one posting 404s, etc) - CONFIRMED in the
same pass: two real Point72 (Greenhouse) postings kept raw_description
as their bare title after a failed detail fetch, and were correctly
scored on title-only information as a result (no crash, no false
signal - just less to search, same as this note used to describe for
every Workday job). So per-job title-only fallback is still possible
on any platform with an enrichment step, just no longer the GUARANTEED
outcome for every job on Workday/SmartRecruiters/pcsx that this note
used to warn about.

WHY A PACKAGE, NOT ONE 1100+ LINE FILE - REORGANIZED 2026-09-06: this
used to be a single scoring.py mixing resume data, text-cleaning
utilities, JD-section detection, hard-filter gating, and the scoring
formula itself all in one growing file. Split by concern instead:

    resume_data.py    - what Aman's resume actually says (RESUME_SKILLS,
                         RESUME_CONTEXT, the keyword-matching regexes)
    text_cleaning.py   - normalizing raw job text before anything else
                         looks at it (HTML, markdown-escaping, spelled-
                         out numbers)
    jd_importance.py   - detecting Required/Preferred sections in a JD
    hard_filters.py     - years/degree/title/competing-stack/framework
                         gating - by far the largest module, and the
                         one that grew the most from real-data testing
    scorer.py           - score_job() itself, tying the above together,
                         plus the resume-independent job filters
                         (is_relevant_title, is_india_location,
                         is_recently_posted)

Every name external code already imports from this package (score_job,
is_relevant_title, is_india_location, is_recently_posted,
REFRESH_WINDOW_HOURS, and strip_html - renamed from the old _strip_html,
since a leading underscore on a name other modules import across a
package boundary was itself a smell not worth carrying into the new
layout) is re-exported below, so every existing `from scoring import
...` elsewhere in the project keeps working completely unchanged.
"""

from .scorer import (
    REFRESH_WINDOW_HOURS,
    is_india_location,
    is_recently_posted,
    is_relevant_title,
    score_job,
)
from .text_cleaning import strip_html

__all__ = [
    "score_job",
    "is_relevant_title",
    "is_india_location",
    "is_recently_posted",
    "REFRESH_WINDOW_HOURS",
    "strip_html",
]
