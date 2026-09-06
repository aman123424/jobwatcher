"""
scoring/resume_data.py
=======================

Aman's actual resume, encoded as data: which skills he has
(RESUME_SKILLS), how much to trust a match on each one
(EVIDENTIAL_SKILLS / RESUME_CONFIDENCE_*), what real experience each
one traces back to (RESUME_CONTEXT), and the regex machinery that
finds them in a job posting's text (_KEYWORD_PATTERNS).

Nothing about JD PARSING lives here (see scoring/jd_importance.py) and
nothing about the SCORING FORMULA lives here (see scoring/scorer.py) -
this module is purely "what does Aman's resume say", independent of
any one job posting.
"""

import re

# Every skill below comes from Aman's actual resume (Aman_Kulwal_Resume.pdf,
# LAST RE-READ 2026-09-05 against the FullStack version updated after
# WiseTech) - either the Technical Skills section, or named directly
# inside an Experience/Projects/Leadership bullet.
#
# CHANGES FROM THE 2026-08-27 VERSION, ALL FROM THE JOBWATCHER PROJECT
# ITSELF NOW BEING A REAL RESUME ENTRY (Aug 2026 onward):
#   - "python" RE-ADDED - was removed 2026-08-28 for not appearing
#     anywhere on the resume; it's back (Languages) AND now has real
#     bullet-level evidence for the first time (see EVIDENTIAL_SKILLS).
#   - "fastapi" ADDED, evidential - JobWatcher's actual backend
#     framework, the tech named in the project's own header line, behind
#     three substantive, real architecture bullets underneath it.
#   - "concurrency" ADDED, evidential - "Applied concurrency throttling
#     to handle rate limiting by sequencing fetches per company while
#     parallelizing across companies" is genuine, specific evidence of
#     real concurrent-programming judgment, not a skill this resume ever
#     claimed before.
#   - "claude code" ADDED, NOT evidential - new Developer Tools entry,
#     but it's a bare tool-list mention with zero bullet elaboration
#     (unlike Copilot, which gets "confirmed strong skill" - Aman's own
#     judgment call, not mine to silently override) - treated the same
#     conservative way as Visual Studio/VS Code below.
#   - "winforms" REMOVED - no longer appears anywhere on the resume (not
#     in Technical Skills, not in any bullet, old or new) - same "don't
#     silently keep stale data" policy that removed python before.
#
# NOTE ON WHY PYTHON/FASTAPI ARE EVIDENTIAL BUT "aws" STILL ISN'T, EVEN
# THOUGH BOTH ONLY APPEAR IN THE JOBWATCHER PROJECT'S HEADER LINE, NOT
# INSIDE A BULLET SENTENCE ITSELF: the existing precedent here was never
# strictly "named inside a bullet" (DigitalOcean IS named inside an
# actual bullet - "deployed on DigitalOcean" - and still isn't
# evidential) - it's "does this skill demonstrate real engineering
# depth, or is it just an infra/deployment choice". Python and FastAPI
# are the substance of three real, detailed architecture bullets
# underneath them (adapter-pattern ingestion, concurrency throttling, a
# ranking model) - AWS Lambda/CloudFront/S3 is just where it's hosted,
# the same category DigitalOcean already falls into. Flagged here
# explicitly since it's a judgment call, not a mechanical rule - revisit
# if this reasoning doesn't hold up.
#
# "agile"/"scrum" (not on the current resume either, old or new) were
# left in at their original low weight since removing them changes
# almost nothing either way.
#
# THREE MORE ADDED 2026-09-06, mined from all 39 training_examples'
# actual reasoning text rather than re-reading the resume again -
# real, evidenced skills the ORIGINAL skills-section-plus-bullets pass
# missed because they're not equipment/language names, they're
# techniques and soft-skills genuinely described in real bullets:
#   - "adapter pattern" - literally "adapter-pattern ingestion layer"
#     in the JobWatcher bullet (NOT the same as the generic "design
#     patterns" entry removed in the 2026-08-28 rewrite for not
#     matching the resume's actual wording - this one now does).
#   - "sprint planning" - literally "managing sprint planning and
#     cross-project prioritization" in the Shaastra Webops bullet.
#     Deliberately its own entry rather than folded into "agile"/
#     "scrum" below - those two words still never appear anywhere on
#     the resume itself, so they stay at their old, low, unverified
#     weight; "sprint planning" is what's actually written down.
#   - "team leadership" - literally "Led a 3-tier team of 20
#     developers" (Shaastra) - a real, resume-evidenced answer to
#     "mentoring"/"team lead"/"people management" asks that nothing in
#     the previous (entirely tools-and-languages) skill list covered.

# Base weight (1-5): how central this skill is to Aman's real profile,
# INDEPENDENT of whether any one job posting treats it as important -
# that's JD_IMPORTANCE (see scoring/jd_importance.py), calculated
# per-job, not baked in here.
RESUME_SKILLS = {
    "c#/.net": 5, "typescript": 4, "react": 4, "javascript": 4, "selenium": 4, "python": 4,
    "typegraphql": 3, "typeorm": 3, "flutter": 3, "graphql": 3, "fastapi": 3,
    "nunit": 3, "moq": 3, "postgresql": 3, "redux": 3, "dsa": 3,
    "system design": 3, "sql": 3, "c++": 3, "node.js": 3, "nodejs": 3,
    "solid principles": 2, "oop": 2, "tdd": 2, "ci/cd": 2, "concurrency": 2,
    "unit test": 2, "integration test": 2, "github": 2, "copilot": 2,
    "html": 2, "css": 2, "docker": 2, "kubernetes": 2, "aws": 2,
    "rest api": 2, "git": 2, "gitlab": 2, "azure devops": 2,
    "spire.pdf": 2, "google oauth": 2, "dart": 2,
    "adapter pattern": 2, "sprint planning": 2, "team leadership": 2,
    "visual studio": 1, "vs code": 1, "digitalocean": 1, "claude code": 1, "agile": 1, "scrum": 1,
}

# WHICH skills above are EVIDENTIAL (get full confidence, see
# RESUME_CONFIDENCE_EVIDENTIAL below) vs left as UNVERIFIED (get half
# confidence, by ELIMINATION - anything in RESUME_SKILLS but not listed
# here). A skill ends up evidential because:
#   (a) it's named directly inside a real bullet describing work Aman
#       actually did (e.g. "c#/.net" - "using C#, .NET" at WiseTech Global)
#   (b) it's the substance behind a real, detailed project's own
#       architecture bullets, even if only named in that project's
#       header line rather than inline in a bullet sentence itself
#       (python, fastapi - see the long comment above RESUME_SKILLS)
EVIDENTIAL_SKILLS = {
    # (a) named directly in a resume bullet
    "c#/.net", "typescript", "react", "selenium", "typegraphql",
    "typeorm", "flutter", "graphql", "nunit", "moq", "postgresql",
    "redux", "spire.pdf", "google oauth", "system design", "ci/cd",
    "unit test", "integration test", "tdd", "github", "copilot", "dsa", "solid principles", "oop",
    "html", "css", "javascript", "concurrency",
    "adapter pattern", "sprint planning", "team leadership",
    # (b) substance of a real project's own architecture, named in its header
    "python", "fastapi",
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
    literals = _KEYWORD_ALTERNATE_SPELLINGS.get(keyword, [keyword])
    alternation = "|".join(re.escape(lit) for lit in literals)
    return re.compile(r"(?<![a-z0-9])(?:" + alternation + r")(?![a-z0-9])")


# A handful of RESUME_SKILLS entries need to match MORE THAN ONE literal
# spelling in job text, while still only ever being counted ONCE - see
# "c#/.net" below. FIXED 2026-08-31: this used to be two entirely
# separate RESUME_SKILLS entries ("c#": 5 and ".net": 5), which meant
# any posting mentioning "C#/.NET" together (the normal way it's ever
# written) got credited TWICE for what is really one real qualification
# - confirmed live on a Rubrik posting where this alone inflated a job
# whose ONLY overlapping skill was a minor "Nice-to-have" C#/.NET
# mention into a 67/100 "Strong match". A job mentioning just "C#"
# alone, or just ".NET" alone, still matches correctly either way -
# this only prevents double-crediting when BOTH spellings appear in the
# same posting (the overwhelmingly common case).
_KEYWORD_ALTERNATE_SPELLINGS = {
    # "dotnet"/"dot net" ADDED 2026-09-06 - a real Zensar posting titled
    # "Developer with DOTNET, AZURE and MS SQL" wrote it as one plain
    # word with no period at all (probably to keep the title
    # URL/filename-safe) - confirmed live this matched NOTHING before,
    # missing the single most important skill in that posting's own title.
    "c#/.net": ["c#", ".net", "dotnet", "dot net"],
    # JDs describing this rarely use the literal word "concurrency" -
    # "multithreading"/"concurrent programming"/"parallel processing"
    # are all the same real skill JobWatcher's own concurrency-
    # throttling bullet demonstrates (see RESUME_SKILLS' comment above).
    "concurrency": ["concurrency", "concurrent programming", "multithreading", "multithreaded", "parallel processing"],
    # Everything below ADDED 2026-09-06, mined from real phrasing
    # variants the training_examples reasoning explicitly credited as
    # equivalent to a RESUME_SKILLS entry, even though the literal
    # dictionary-key string never appeared in that JD's own text -
    # e.g. a JD saying "Web APIs" or "RESTful APIs" was credited the
    # same as one literally saying "REST API". Kept as SAFE, specific
    # compound phrases only (never a single common English word alone)
    # for the same false-positive reason _compile_keyword_pattern's own
    # docstring gives for "aws" inside "laws" - "solid" or "go" alone
    # would be far too noisy to add here.
    # Plural forms included explicitly, not just the singular - the
    # word-boundary lookahead in _compile_keyword_pattern rejects a
    # match immediately followed by another letter/digit, so "REST
    # api" does NOT match inside "REST APIs" (trailing "s") without
    # its own separate plural entry - confirmed live testing this
    # exact gap against "Experience building RESTful APIs" (plural),
    # which silently matched nothing at all before this fix.
    "rest api": ["rest api", "rest apis", "restful api", "restful apis", "web api", "web apis"],
    # "unit tests"/"integration tests" (plural) are PRE-EXISTING gaps,
    # not new ones - found while checking the "rest api" plural bug
    # above for the same root cause elsewhere. Confirmed live: "Writes
    # clean unit tests" matched NOTHING before this fix, despite "unit
    # test" already being a tracked, evidential, weight-2 skill.
    "unit test": ["unit test", "unit tests", "unit testing"],
    "integration test": ["integration test", "integration tests"],
    "oop": ["oop", "object-oriented", "object oriented"],
    "solid principles": ["solid principles", "solid design principles", "single responsibility principle"],
    # "Claude CLI" is a real phrasing variant seen for "Claude Code"
    # specifically (#9/#12/#20/#30 in the mining pass all treat
    # "AI-assisted development/engineering tools including GitHub
    # Copilot and Claude Code/CLI" as a literal match, not a stretch).
    "copilot": ["copilot", "github copilot"],
    "claude code": ["claude code", "claude cli"],
}

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
    "c#/.net": "2 years hands-on C#/.NET at WiseTech Global (AE Customs, UAE Manifest workflows)",
    "python": "Python - the language JobWatcher itself (this project) is built in, behind its adapter-pattern ATS ingestion layer and ranking model",
    "fastapi": "FastAPI - JobWatcher's own backend framework, serving its 50+-company job ingestion pipeline",
    "concurrency": "Concurrency throttling in JobWatcher - sequencing fetches per company while parallelizing across companies to handle rate limits",
    "adapter pattern": "Adapter-pattern ingestion layer in JobWatcher, reconciling 6+ divergent ATS APIs into one unified schema",
    "sprint planning": "Managed sprint planning and cross-project prioritization leading Webops Core at Shaastra, IIT Madras",
    "team leadership": "Led a 3-tier team of 20 developers delivering 14+ websites and a mobile app for Shaastra, IIT Madras",
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
    "claude code": "Claude Code - listed Developer Tools skill, not resume-bullet-evidenced",
}
