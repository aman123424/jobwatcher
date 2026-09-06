"""
scoring/hard_filters.py
=========================

Everything that can cap or discount a score REGARDLESS of how good the
raw keyword overlap looked: years-of-experience and degree
requirements Aman clearly doesn't meet, a title implying a seniority
level well above his own, and postings built around a technology
ecosystem (or, more narrowly, a specific framework) he has no real
exposure to.

The single entry point other modules call is _apply_hard_filters() at
the bottom of this file - everything above it is the regexes and
tuning constants that function relies on, each with its own real
before/after story in its comment (a specific posting that either
false-positived or was missed entirely before that fix).
"""

import re

# =============================================================================
# HARD FILTERS (years of experience / degree requirements)
# =============================================================================
# Aman's real total professional experience, used as the baseline below.
# ~2 years, per WiseTech Global's July 2024 - May 2026 dates on his resume.
BASELINE_YEARS_EXPERIENCE = 2

# How many years ABOVE the baseline a posting can require before we treat
# it as a real mismatch (rather than just "a bit senior but plausible").
YEARS_OVER_BASELINE_TO_GATE = 3

# Matches "5+ years", "5-8 years", "2 years", "1.5+ years", etc.
#
# DECIMAL YEARS - CONFIRMED REAL BUG, FOUND 2026-09-06 testing against
# 50 real postings: a real Affirm posting states "1.5+ years of
# experience" (a genuinely LOW, near-entry-level bar) - the previous
# version of this regex, `(\d+)` with no decimal support, can't match
# "1.5" as one number. Worse than just failing to match: the regex
# engine backtracks and finds a DIFFERENT match starting at the "5" in
# "1.5", producing "5+ years" - completely inverting the posting's real
# meaning (a floor of 1.5 read as a floor of 5) and capping an
# excellent, level-appropriate match down to 18. `(?:\.\d+)?` on both
# the base number and the upper end of a range fixes this by capturing
# the WHOLE decimal number, not just the digits after the point.
#
# "yrs" ABBREVIATION - CONFIRMED REAL BUG, found 2026-09-06 testing 123
# real postings from our own 47 target companies: a Graviton posting
# ("3-5 yrs Experience with C/C++...") never matched at all because the
# old pattern only accepted "years?" - "yrs" is a common enough real
# abbreviation (5 occurrences across the two most recent real-data
# passes) that it's worth a second word, not a one-off to ignore.
_YEARS_REQUIREMENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\+|-\s*\d+(?:\.\d+)?)?\s*(?:years?|yrs?)", re.IGNORECASE)

# CONFIRMED REAL BUG, FIXED 2026-09-06 (this used to be called "a known,
# accepted limitation" - it stopped being acceptable once it was
# actually confirmed live): re-testing against 22 fresh real postings
# found a JPMorgan posting - "our history spans over 200 years" - and a
# PayPal one - "PayPal has been revolutionizing commerce globally for
# more than 25 years" - both pure company-history boilerplate, captured
# as literal 200-year and 25-year EXPERIENCE REQUIREMENTS, gating two
# otherwise strong matches (real Python/React/TypeScript overlap on the
# JPMorgan one) down to a score of 2. Fixed by requiring the word
# "experience" within _YEARS_EXPERIENCE_PROXIMITY_CHARS of the match,
# checked on EITHER side (real requirement phrasings go both ways -
# "3+ years of experience" has it after, "Experience: 2-4 Years" has it
# before) - company-history sentences essentially never have
# "experience" sitting right next to the number, they move on to
# unrelated marketing copy instead.
_YEARS_EXPERIENCE_PROXIMITY_CHARS = 50

_EXPERIENCE_SINGULAR_RE = re.compile(r"experience(?!s)", re.IGNORECASE)


def _years_match_is_real_requirement(haystack: str, match: re.Match) -> bool:
    """
    A SECOND real false-positive found testing this exact fix against a
    real PayPal posting: "PayPal has been revolutionizing commerce
    globally for more than 25 years. Creating innovative EXPERIENCES
    that make moving..." - plain substring matching on "experience"
    matches inside "experiences" too, and marketing copy about product/
    user EXPERIENCES (plural) sits right next to this exact kind of
    company-history sentence far more often than genuine requirement
    text does. A real requirement clause is always singular -
    "years of experience", "years experience", "years relevant
    experience" - never "years of experiences" - so the singular-only
    check below is a real, evidence-based distinction, not a guess.
    """
    window_start = max(0, match.start() - _YEARS_EXPERIENCE_PROXIMITY_CHARS)
    window_end = min(len(haystack), match.end() + _YEARS_EXPERIENCE_PROXIMITY_CHARS)
    return bool(_EXPERIENCE_SINGULAR_RE.search(haystack[window_start:window_end]))


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

# When the DEGREE gate fires (a real gap with no escape clause), the
# score gets CAPPED at this ceiling, not just discounted - mirroring
# how Claude's manual reasoning treated this as "near-automatic low
# score, regardless of how good the rest looked." Kept flat (unlike the
# years gate below) since there's no natural "how big is the gap" axis
# for a degree requirement the way there is for years - either Aman has
# the required degree tier or he doesn't.
HARD_GATE_SCORE_CEILING = 30

# YEARS-GATE CEILING, SCALED BY GAP SIZE - REWORKED 2026-09-06 after
# mining all 39 training_examples' actual reasoning text (see
# PROJECT_LOG.md / conversation log for the full extraction). The old
# version capped EVERY years-gate at the same flat 30, whether a
# posting wanted 5 years or 15 - Aman's own stated ask, and the real
# reasoning transcripts, both treat these as very different severities:
#   - "5+ yrs, or Master's+4, no equivalency clause at all" -> 12%
#     (#24 in the mining pass - "not close on either path")
#   - "6+ years... Senior... Java+Python+Kafka+K8s" -> 5% (#34 -
#     "less than a third of the floor... not adjacent in any dimension")
#   - "8 years" / "4-8 years, AVP-level" -> 1% (#37/#38 - "the years and
#     title alone rule it out immediately")
# Keyed by GAP (years required - BASELINE_YEARS_EXPERIENCE), not the
# raw years number, so this stays correct even if BASELINE_YEARS_EXPERIENCE
# changes later as Aman gains real experience. This is a ceiling
# (min(pct, ceiling)), not a forced value - a posting whose raw keyword
# score is ALREADY below the ceiling (e.g. a Kafka/Java-heavy posting
# with almost no overlap with RESUME_SKILLS to begin with) is untouched
# by it either way; the ceiling only matters for the specific case Aman
# asked about - a genuinely strong stack match wrapped in a seniority
# level well above his own.
_YEARS_GATE_CEILING_TIERS = [
    # (max gap this tier covers, ceiling)  - checked in order, first match wins
    (4, 18),   # gap 3-4  (e.g. "5-6 years required") - matches #24's 12%
    (6, 8),    # gap 5-6  (e.g. "7-8 years required") - matches #34's 5%
    (999, 2),  # gap 7+   (e.g. "9+ years", AVP/Director-level) - matches #37/#38's 1%
]


def _years_gate_ceiling(years_required: float) -> int:
    gap = years_required - BASELINE_YEARS_EXPERIENCE
    for max_gap, ceiling in _YEARS_GATE_CEILING_TIERS:
        if gap <= max_gap:
            return ceiling
    return _YEARS_GATE_CEILING_TIERS[-1][1]  # unreachable given the 999 catch-all above, kept for clarity


# CONFIRMED REAL GAP, found 2026-09-06 testing 123 real postings from our
# own 47 target companies: the hard years gate only fires at gap >= 3
# (years_required >= 5, since BASELINE_YEARS_EXPERIENCE=2 and
# YEARS_OVER_BASELINE_TO_GATE=3) - a plain "3+ years" or "4+ years"
# requirement (a real, common Amazon/Microsoft phrasing) got ZERO
# penalty at all, cliff-edging straight from "no gate" to "hard gate"
# with nothing in between. Real Amazon SDE II postings stating "3+
# years of non-internship professional software development
# experience" scored 85-97 here purely on keyword overlap while the
# LLM, reading the same postings, consistently landed in the 25-45
# range - not zero-penalty, but not disqualifying either; "a real but
# not extreme shortfall" was the recurring phrase. This fills that gap
# with a soft, proportional discount (same shape as
# BARE_SENIOR_TITLE_DISCOUNT) for a requirement 1-2 years over
# baseline, leaving the existing hard gate at 3+ years over baseline
# untouched.
MODERATE_YEARS_GAP_DISCOUNT = 0.55


# Words in a job TITLE that suggest a seniority level well above
# Aman's current ~2 years. This is a separate, simpler check from the
# keyword scorer — title-based, not description-based, because
# seniority words in a title are a strong, low-noise signal ("Staff
# Software Engineer" almost always IS a Staff-level role), whereas the
# same words buried in a long description are much noisier.
SENIOR_TITLE_WORDS = ["staff", "principal", "director", "head of", "vp",
                      "vice president", "lead", "architect"]

# CONFIRMED REAL BUG, found 2026-09-06 testing 100 real postings against
# LLM reasoning: an "IT Intern / Full Stack Developer Intern" posting
# (student-targeted, stipend-only, no real YOE floor to catch it) scored
# 97/100 here vs 15/100 from the LLM - the word "intern" in the title
# was ALREADY detected (see _build_reason()'s "internship level" caveat
# and _infer_seniority() below), but only as caveat TEXT, never fed back
# into match_score itself. This is the same class of bug the "Senior/
# Staff" title-only gate above already fixes for the opposite direction
# (overqualified for the title, not underqualified) - a mismatch this
# large and this cheaply detectable shouldn't need a body-text years
# number to catch it. Separate, lower ceiling from HARD_GATE_SCORE_CEILING
# since this is a role-TYPE mismatch (Aman is past this level entirely),
# not a "close but capped" years/degree gap.
INTERNSHIP_TITLE_RE = re.compile(r"(?<![a-z])(intern|internship|trainee)(?![a-z])", re.IGNORECASE)
INTERNSHIP_SCORE_CEILING = 20

# A BARE "senior"/"sr" title, on its own, WITHOUT a scary explicit years
# number anywhere in the body - ADDED 2026-09-06, a real gap the mining
# pass surfaced: two otherwise-identical postings for the same real
# team, one titled plainly and one titled "Senior", scored 58 vs 38 in
# the actual reasoning transcripts (a job's own title implying "we
# expect more than ~2 years" even with no explicit number stated) - but
# "senior"/"sr" was NEVER in SENIOR_TITLE_WORDS above, so the old code
# had literally no mechanism to reproduce this at all; a bare "Senior"
# title changed nothing. This is DELIBERATELY a softer penalty (a
# proportional discount, not a hard ceiling) than SENIOR_TITLE_WORDS
# above ("staff"/"principal"/"director"/...) - "Senior Software
# Engineer" is a real, sometimes-worth-trying reach the way "Staff" or
# "Director" isn't, matching the ~35% relative reduction (58->38) seen
# in the real transcript, not a near-total wipeout.
BARE_SENIOR_TITLE_DISCOUNT = 0.65
_BARE_SENIOR_TITLE_RE = re.compile(r"(?<![a-z])(senior|sr\.?)(?![a-z])", re.IGNORECASE)

# NUMBERED TITLE LEVELS ("Software Engineer III", "SDE II", "Engineer
# Level 4") - ADDED 2026-09-06, found by re-testing against 22 fresh
# real postings: JPMorgan (and many large companies) signal seniority
# via a roman-numeral/level suffix instead of the word "senior" at all,
# which BARE_SENIOR_TITLE_DISCOUNT above has no way to catch. Confirmed
# live across the JPMorgan batch: "Software Engineer II" postings
# stated a 2+ year floor (matching Aman's own level, no penalty
# warranted), while every "Software Engineer III" posting in the same
# batch stated a 3+ year floor and read, in real reasoning, as "a real
# seniority gap" - so II is treated as neutral (roughly Aman's own
# level) and III-or-higher gets the SAME treatment as a bare "Senior"
# title (soft discount, escalated to the harder gate if leadership-
# scope language is also present - see bare_senior_with_leadership_scope
# in _apply_hard_filters() below, which this feeds into identically).
_NUMBERED_LEVEL_RE = re.compile(
    r"\b(?:engineer|developer|sde)\s+(iii|iv|v|vi|[3-9])\b",
    re.IGNORECASE,
)

# ESCALATION - ADDED 2026-09-06 after re-testing this package's OWN
# changes against a real stored example (a real ABB posting, in
# training_examples): a bare "Sr Software Engineer" title whose BODY
# text ALSO says "extensive experience... to lead," "drive technical
# strategy," "mentor engineering teams," "define architectural best
# practices" is a technical-LEAD role wearing a plain "Senior" title,
# not an ordinary senior IC opening - Claude's own real reasoning on
# this exact posting: "Score: 15-20%... genuinely strong stack overlap
# on paper, undercut hard by seniority and leadership scope." The bare
# BARE_SENIOR_TITLE_DISCOUNT alone (0.65x) only pulled a 97 down to 63
# on this real posting - nowhere near the real 15-20% - because a soft
# proportional discount can't represent "this is actually a lead role"
# the way the harder SENIOR_TITLE_WORDS gate (ceiling 30) can. So: a
# bare senior/sr title is escalated to that SAME harder gate, not just
# the soft discount, whenever the BODY text also carries real
# leadership-scope language - checked as its own thing rather than
# folding "lead" into SENIOR_TITLE_WORDS itself, since "lead" the WORD
# in a title (e.g. "Lead Engineer") is a much lower-noise signal than
# "lead"/"leadership" language scattered through a job's body text.
_LEADERSHIP_SCOPE_RE = re.compile(
    r"(to\s+lead\s+the|drive\s+(the\s+)?technical\s+strategy|mentor\s+(engineering\s+)?teams?|"
    r"define\s+architectural|own\s+the\s+architecture|technical\s+leadership)",
    re.IGNORECASE,
)

# How close (in characters) a genuine escape clause needs to be to the
# SPECIFIC years/degree requirement it's meant to excuse, to count as
# applying to it. Without this, a posting with a valid escape clause
# for its degree requirement (like Twilio's) would incorrectly excuse
# an entirely separate, unrelated years requirement stated elsewhere in
# the same posting - a real bug found and fixed alongside this file.
ESCAPE_CLAUSE_PROXIMITY_CHARS = 200

# COMPETING PRIMARY STACK - ADDED 2026-09-06 from the single most
# common rejection pattern across all 39 training_examples: a posting
# built entirely on a specific backend ecosystem Aman has zero real
# exposure to, wrapped in a generic "Software Engineer" title that a
# pure keyword-overlap scorer has no way to catch on its own (a couple
# of incidental "OOP"/"Git"/"testing" mentions can otherwise inflate an
# entirely wrong-ecosystem posting). Direct quotes from the mining
# pass: Java/Spring Boot postings - "same Java wall... different team,
# different stack" (recurring across 7+ of the 39, the single largest
# rejection category); Salesforce/Apex - "Apex isn't a general-purpose
# language you can claim transferable OOP knowledge toward"; COBOL -
# "a completely separate technology era"; Golang-for-identity - "would
# need actual hands-on... experience in identity engineering first".
#
# CORRECTED 2026-09-06: an earlier version of this comment claimed bare
# "java" "would match inside javascript" and excluded it for that
# reason - but that reasoning was WRONG, and confirmed wrong by testing
# this package's own changes against 22 fresh real postings (Apple,
# JPMorgan 210765090, Optum, Cisco 2016608 all require plain "Java" -
# not "Spring Boot" - and every one of them scored 97/100 uncaught).
# _compile_keyword_pattern's own word-boundary lookaround (see
# resume_data.py), used EVERYWHERE ELSE in this package, already makes
# "java" immediately followed by "Script" fail to match (the lookahead
# requires the next character NOT be a letter) - the exact same
# mechanism that already lets "javascript" itself be one of Aman's own
# recognized languages below without colliding. Bare "go" is still
# excluded - unlike "java", it's an ordinary English word ("go
# through", "going forward") with no equivalent safe way to bound it,
# so "golang" stays the only Go signal. Native iOS (Swift/Objective-C/
# Xcode) ADDED after the same real-data pass found a JPMorgan posting
# requiring "Swift," "Objective-C," and "Xcode" scoring 34 uncaught - a
# different technology discipline (native mobile) Aman has zero
# evidence of, same severity as the backend-ecosystem mismatches above.
#
# "php" ADDED 2026-09-06 - found testing against 50 real LinkedIn/
# Indeed postings: a "Senior Full Stack Engineer - PHP" posting
# ("Extensive experience with modern PHP" as the first required
# bullet) scored 63/100, with nothing at all recognizing PHP as a
# language Aman has zero exposure to. Safe as a bare word the same way
# "java" is (real word, not a fragment of a longer common word the way
# bare "go" would be).
#
# "rust" ADDED 2026-09-06 - CONFIRMED REAL BUG testing against 100 real
# postings: an Antier posting for low-latency trading infrastructure
# ("build... in Rust", "3+ years... with systems-level work") scored
# 75/100 (LLM: 4) - Aman has never written Rust, but the only language
# in _OWN_PRIMARY_LANGUAGE_RE/RESUME_SKILLS the JD ALSO happened to
# mention (C++, offered as an alternate) matched fine, so nothing here
# ever recognized Rust itself as the actual, non-negotiable core ask.
# Safe as a bare word (not an English word fragment like bare "go").
_COMPETING_STACK_RE = re.compile(
    r"((?<![a-z0-9])java(?![a-z0-9]|script)|spring\s*boot|golang|cobol|"
    r"salesforce\s*apex|apex\s+(class|classes|trigger|triggers|development)|"
    r"(?<![a-z0-9])swift(?![a-z0-9])|objective-c|(?<![a-z0-9])xcode(?![a-z0-9])|"
    r"(?<![a-z0-9])php(?![a-z0-9])|(?<![a-z0-9])rust(?![a-z0-9]))",
    re.IGNORECASE,
)

# COMPETING FRAMEWORK (NOT LANGUAGE) - ADDED 2026-09-06, a DIFFERENT
# and softer category from _COMPETING_STACK_RE above. Found testing
# against 50 real postings: Django showed up as a named, required
# framework in multiple Python-backend postings (Defaqto, Trafalgar
# House) - Python itself is genuinely one of Aman's languages (via
# JobWatcher's FastAPI backend), so _OWN_PRIMARY_LANGUAGE_RE correctly
# does NOT treat these as a competing-stack case the way Java/PHP/Go
# would be - the LANGUAGE is right. But Django and FastAPI are
# different frameworks with different patterns (ORM/MVT vs async/
# dependency-injection), and Aman has zero Django exposure - real
# reasoning docked these postings for exactly that ("Django is the
# load-bearing framework... Aman has zero Django experience"), which
# this package had no way to represent at all before this. DELIBERATELY
# a softer discount (same tier as BARE_SENIOR_TITLE_DISCOUNT), not a
# hard ceiling like _COMPETING_STACK_RE - the right LANGUAGE background
# is real, transferable partial credit, just not a framework-level match.
_COMPETING_FRAMEWORK_DISCOUNT = 0.7
_COMPETING_FRAMEWORK_RE = re.compile(r"(?<![a-z0-9])django(?![a-z0-9])", re.IGNORECASE)

# Genuine escape for the Django check above: Aman's OWN Python
# framework (FastAPI), or Flask (the other common "pick one" Python
# web framework a real OR-list names alongside Django). NOT the same
# bypass list as _OWN_PRIMARY_LANGUAGE_RE - CONFIRMED BUG found testing
# this exact fix against real data: "The role focuses on Python and
# Django development" (Trafalgar House) has "python" sitting right next
# to "django" by definition (Django IS a Python framework - the
# language will ALWAYS be nearby), so reusing the language-proximity
# bypass here would make this gate never fire at all. Only a genuine
# alternative FRAMEWORK nearby is a real escape.
_OWN_PYTHON_FRAMEWORK_RE = re.compile(r"(?<![a-z0-9])(fastapi|flask)(?![a-z0-9])", re.IGNORECASE)

# Aman's own real primary languages - if one of these appears NEAR a
# _COMPETING_STACK_RE match (see COMPETING_STACK_PROXIMITY_CHARS below),
# that specific occurrence does NOT gate: that's the genuinely common
# "polyglot" or "any of X/Y/Z" case (see the mining pass's #14 - "it's
# an 'or' list, not an 'and' list, Python alone satisfies this") rather
# than a posting truly built around a stack Aman has no foothold in.
#
# PROXIMITY-BASED, NOT WHOLE-DOCUMENT - REWORKED 2026-09-06 after TWO
# separate confirmed false-bypasses on real postings, both the same
# root cause: checking "does this language appear ANYWHERE in the
# document" instead of "does it appear as part of THIS SAME
# requirement": (1) an Apple posting requiring "Java/J2EE... Spring
# Boot" (backend, mandatory) also separately listed "JavaScript,
# NodeJS, React" for the FRONTEND - whole-document presence of
# "javascript" wrongly cancelled the Java gate. (2) A Cisco posting -
# "Must have good experience with Java/J2EE and/or GO and REST...
# Experience with Spring, Spring boot, Python along with..." - Python
# is a SEPARATE required skill listed after the Java/Go requirement,
# not an alternative TO it, but whole-document presence of "python"
# wrongly cancelled the gate anyway, even after (1) was already fixed.
# Both are fixed the same way: an own-language only cancels a
# COMPETING_STACK match if it's genuinely nearby (same requirement/
# sentence), not simply present somewhere else in a multi-page posting.
#
# "javascript" DELIBERATELY EXCLUDED from this list - the same Apple
# false-bypass above is exactly why: a JD naming both Java (backend)
# and JavaScript (frontend) almost always means "Java backend +
# JS-ecosystem frontend," two unrelated requirements, not a real choice
# between them. "python"/"c#"/"typescript"/"c++" stay in this list -
# those DO commonly appear as genuine backend alternatives in a real
# "Java, Python, or Go" style OR-list (see Optum's real posting,
# correctly NOT gated by this list).
_OWN_PRIMARY_LANGUAGE_RE = re.compile(
    r"(?<![a-z0-9])(c#|\.net|python|typescript|c\+\+)(?![a-z0-9])",
    re.IGNORECASE,
)

# How close (in characters) an own-primary-language mention needs to be
# to a competing-stack term to count as "the same OR-list", not just
# "also mentioned somewhere in this posting" - same proximity principle
# as ESCAPE_CLAUSE_PROXIMITY_CHARS above, applied to this gate instead.
COMPETING_STACK_PROXIMITY_CHARS = 60

# Lower than HARD_GATE_SCORE_CEILING (30) - the mining pass's actual
# competing-stack rejections scored 1-5%, well below the generic
# years/degree gate ceiling, matching "not adjacent in any dimension
# that matters" rather than "a stretch, but maybe with a referral".
COMPETING_STACK_SCORE_CEILING = 15


def _apply_hard_filters(haystack: str, title: str, pct: int) -> tuple[int, str | None]:
    """
    Checks for a years-of-experience or degree requirement Aman clearly
    doesn't meet, WITH no "or equivalent experience" escape clause found
    NEAR that specific requirement (not just anywhere in the whole
    document - see ESCAPE_CLAUSE_PROXIMITY_CHARS above for why that
    distinction matters). CONFIRMED CORRECT against the mining pass:
    every training_examples case with a genuine nearby "or equivalent...
    experience" clause scored 30-68% DESPITE being under the stated
    years floor - the escape clause is meant to fully excuse the gate,
    not just soften it, and that's what this already does. Only the
    NO-escape-clause severity needed reworking (see
    _years_gate_ceiling() above) - if found, caps pct at a ceiling that
    scales with how far over the years requirement is, not a flat
    value. Returns (possibly-adjusted pct, which gate fired - "years",
    "degree", "title", "bare_senior", "competing_stack",
    "competing_framework", or None) - the second value lets
    scorer.py's _build_reason() phrase the caveat correctly (a hard cap
    reads very differently from a proportional discount).

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
    experience" clause elsewhere would plausibly override. A BARE
    "senior"/"sr" title (see BARE_SENIOR_TITLE_DISCOUNT above) gets a
    separate, softer proportional discount instead of this hard gate -
    checked only when nothing harder already fired, so a title like
    "Senior Staff Engineer" still gets the harder SENIOR_TITLE_WORDS
    treatment, not double-penalized by both.
    """
    if INTERNSHIP_TITLE_RE.search(title):
        return min(pct, INTERNSHIP_SCORE_CEILING), "internship"

    escape_positions = [m.start() for m in _EQUIVALENT_EXPERIENCE_RE.finditer(haystack)]

    def has_nearby_escape(position: int) -> bool:
        return any(abs(position - escape_pos) <= ESCAPE_CLAUSE_PROXIMITY_CHARS for escape_pos in escape_positions)

    # Track the LARGEST gating years-requirement found, not just "did
    # any gate at all" - that's what _years_gate_ceiling() needs to
    # scale the ceiling correctly. A posting stating both "3+ years" and
    # "8+ years for senior track" should be judged against the 8, not
    # whichever number the regex happened to reach first.
    years_gate = False
    max_gating_years = 0
    moderate_years_gap = False
    for m in _YEARS_REQUIREMENT_RE.finditer(haystack):
        if not _years_match_is_real_requirement(haystack, m):
            continue  # company-history boilerplate ("spans over 200 years"), not a real requirement
        years = float(m.group(1))  # float, not int - "1.5+ years" is a real, valid requirement (see _YEARS_REQUIREMENT_RE's own comment)
        if has_nearby_escape(m.start()):
            continue
        if years >= BASELINE_YEARS_EXPERIENCE + YEARS_OVER_BASELINE_TO_GATE:
            years_gate = True
            max_gating_years = max(max_gating_years, years)
        elif years > BASELINE_YEARS_EXPERIENCE:
            moderate_years_gap = True

    degree_match = _DEGREE_REQUIRED_RE.search(haystack)
    degree_gate = bool(degree_match) and not has_nearby_escape(degree_match.start())

    title_lower = title.lower()
    title_gate = any(w in title_lower for w in SENIOR_TITLE_WORDS)
    # A bare "senior"/"sr" title ALONE is the softer discount below, but
    # paired with real leadership-scope language in the body (see
    # _LEADERSHIP_SCOPE_RE's own comment for the real example that
    # surfaced this), it's escalated to the same harder gate as
    # SENIOR_TITLE_WORDS - a "Sr Software Engineer... to lead the
    # development... mentor engineering teams" posting is a lead role,
    # not an ordinary senior IC opening.
    # A numbered level (e.g. "Software Engineer III") is treated exactly
    # like a bare senior/sr title from here on - same soft-discount
    # default, same escalation to the harder gate when leadership-scope
    # language is present (see _NUMBERED_LEVEL_RE's own comment above).
    seniority_signal_present = bool(_BARE_SENIOR_TITLE_RE.search(title_lower)) or bool(_NUMBERED_LEVEL_RE.search(title_lower))
    bare_senior_with_leadership_scope = seniority_signal_present and bool(_LEADERSHIP_SCOPE_RE.search(haystack))

    # A posting built around a stack Aman has no real foothold in at
    # all (see COMPETING_STACK_SCORE_CEILING's own comment above) -
    # checked BEFORE years/degree/title below since this is a different
    # KIND of mismatch (technology ecosystem, not seniority) that can
    # coexist with an otherwise-reasonable years requirement.
    own_language_positions = [m.start() for m in _OWN_PRIMARY_LANGUAGE_RE.finditer(haystack)]

    def has_nearby_own_language(position: int) -> bool:
        return any(abs(position - p) <= COMPETING_STACK_PROXIMITY_CHARS for p in own_language_positions)

    competing_stack_gate = any(
        not has_nearby_own_language(m.start()) for m in _COMPETING_STACK_RE.finditer(haystack)
    )

    if competing_stack_gate:
        return min(pct, COMPETING_STACK_SCORE_CEILING), "competing_stack"
    if years_gate:
        return min(pct, _years_gate_ceiling(max_gating_years)), "years"
    if degree_gate:
        return min(pct, HARD_GATE_SCORE_CEILING), "degree"
    if title_gate or bare_senior_with_leadership_scope:
        return min(pct, HARD_GATE_SCORE_CEILING), "title"

    # Below this point, nothing HARD fired - only soft, multiplicative
    # discounts remain (bare senior/numbered-level title, competing
    # framework within an otherwise-right language). Combined
    # multiplicatively, not "first one wins" - a posting that's BOTH a
    # bare "Senior" title AND Django-required is a real double concern,
    # not just one or the other (e.g. Trafalgar House's "Senior... Django
    # Developer" case from the 2026-09-06 real-data pass).
    django_match = _COMPETING_FRAMEWORK_RE.search(haystack)
    own_framework_positions = [m.start() for m in _OWN_PYTHON_FRAMEWORK_RE.finditer(haystack)]
    competing_framework_gate = bool(django_match) and not any(
        abs(django_match.start() - p) <= COMPETING_STACK_PROXIMITY_CHARS for p in own_framework_positions
    )
    # Gate names are joined with "_and_" rather than enumerated as
    # combinatorial dict keys - see scorer.py's _GATE_CAVEAT_TEXT, which
    # looks up each atomic name here and stitches the sentences
    # together, so adding a new soft discount (like moderate_years_gap
    # below) never requires adding every pairwise/triple combination by
    # hand.
    discount = 1.0
    gate_parts = []
    if seniority_signal_present:
        discount *= BARE_SENIOR_TITLE_DISCOUNT
        gate_parts.append("bare_senior")
    if competing_framework_gate:
        discount *= _COMPETING_FRAMEWORK_DISCOUNT
        gate_parts.append("competing_framework")
    if moderate_years_gap:
        discount *= MODERATE_YEARS_GAP_DISCOUNT
        gate_parts.append("moderate_years_gap")
    if discount < 1.0:
        return round(pct * discount), "_and_".join(gate_parts)

    return pct, None
