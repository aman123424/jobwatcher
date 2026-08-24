"""
scoring.py
==========

Takes a normalized job (from fetchers.py) and produces a 0-100 "match
score" against Aman's resume, plus a short human-readable reason.

HOW IT WORKS (and why this approach, specifically):
This is a WEIGHTED KEYWORD OVERLAP scorer — we keep a list of skills
from the resume, each with a "weight" (how strongly it should count),
and check how many of those keywords appear in the job's title +
description. It is the same approach used earlier in this project for
the LinkedIn/Naukri spreadsheet, kept consistent here so scores mean
the same thing across every part of the system.

BE HONEST ABOUT WHAT THIS IS NOT:
This is NOT semantic understanding. It cannot tell that "ASP.NET Core"
and ".NET" are the same ecosystem unless we've explicitly listed both.
It cannot tell that a job wanting "5+ years" is a bad fit for someone
with ~2 years of experience — that's handled separately, by looking at
the title for seniority words (see `infer_seniority` below), not by
this scoring function. A high score means "this job's text shares a
lot of vocabulary with the resume" — a reasonable proxy for fit, but
a proxy, not a guarantee. The match_reason string exists specifically
so a human (Aman) can sanity-check the score in a few seconds rather
than trust the number blindly.
"""

import re

# --- Resume skill weights -----------------------------------------------
# Higher weight = more central to Aman's actual experience (from his
# resume), not just "any technology he's heard of". For example C# and
# .NET are weighted highest because his entire WiseTech Global role was
# built on them; "agile"/"scrum" are weighted lowest because almost
# every job description mentions them regardless of actual fit.
RESUME_SKILLS = {
    "c#": 5, ".net": 5, "winforms": 3, "selenium": 4, "nunit": 3, "moq": 3,
    "react": 4, "typescript": 4, "javascript": 4, "python": 3, "sql": 3,
    "c++": 3, "flutter": 3, "node.js": 3, "nodejs": 3,
    "git": 2, "github": 2, "gitlab": 2, "copilot": 2,
    "tdd": 2, "oop": 2, "design patterns": 2, "system design": 2,
    "unit test": 2, "integration test": 2, "ci/cd": 2,
    "agile": 1, "scrum": 1,
}
MAX_POSSIBLE_SCORE = sum(RESUME_SKILLS.values())

# Short, plain-English explanation of WHERE each keyword comes from in
# Aman's actual background. Used to build the match_reason string, so
# the output says something like "2 years hands-on C#/.NET at WiseTech
# Global" instead of just repeating the bare keyword "c#".
RESUME_CONTEXT = {
    "c#": "2 years hands-on C#/.NET at WiseTech Global",
    ".net": "2 years hands-on .NET/WinForms at WiseTech Global",
    "winforms": "WinForms experience from CargoWise work",
    "selenium": "Selenium test automation experience (NUnit/Moq)",
    "nunit": "NUnit testing background",
    "moq": "Moq mocking framework experience",
    "react": "React experience from Clueso/Desklamp internships",
    "typescript": "TypeScript from Desklamp/Shaastra projects",
    "javascript": "JavaScript across web projects",
    "python": "Python coursework/project exposure",
    "sql": "SQL used in CargoWise data pipelines",
    "git": "Git/GitHub workflow experience",
    "github": "GitHub/GitHub Copilot experience",
    "ci/cd": "CI/CD pipeline exposure at WiseTech",
    "node.js": "Node.js from Clueso internship (FastAPI/Next.js stack)",
    "nodejs": "Node.js experience",
    "tdd": "TDD practice at WiseTech",
    "design patterns": "SOLID/Design Patterns application",
    "system design": "System design coursework/practice",
    "flutter": "Flutter (InstiSpace app, 11k+ users)",
    "c++": "C++ / DSA background from IIT Madras",
}

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
    """
    title = job.get("title", "") or ""
    description = _strip_html(job.get("raw_description", ""))
    haystack = f"{title} {description}".lower()

    matched_keywords = [kw for kw in RESUME_SKILLS if kw in haystack]
    raw_score = sum(RESUME_SKILLS[kw] for kw in matched_keywords)

    # Scale raw_score (which maxes out around MAX_POSSIBLE_SCORE, but
    # realistically no single job description will contain EVERY skill
    # on the resume) up to a 0-100 range. The *1.8 multiplier is a
    # calibration constant carried over from the earlier LinkedIn/
    # Naukri version of this scorer — found by checking that a
    # genuinely strong match (5-6 matched keywords) lands around
    # 60-80, not clustered near single digits. This is a heuristic,
    # not a statistically derived constant — if scores start feeling
    # systematically too high or low once you see real results, this
    # is the number to adjust.
    pct = round(min((raw_score / MAX_POSSIBLE_SCORE) * 100 * 1.8, 97))

    job["match_score"] = pct
    job["match_reason"] = _build_reason(title, matched_keywords, pct)
    job["seniority"] = _infer_seniority(title)
    return job


def _build_reason(title: str, matched_keywords: list[str], score: int) -> str:
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
