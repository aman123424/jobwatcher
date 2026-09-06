"""
scoring/text_cleaning.py
=========================

Normalizes raw job-posting text BEFORE any keyword/JD-importance/
hard-filter pattern in this package ever looks at it. Every fix here
was found the same way: a real skill or requirement was invisible to
every downstream pattern purely because of how the SOURCE encoded that
text, not because the pattern itself was wrong.
"""

import html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """
    Greenhouse's job descriptions come back as HTML (e.g.
    "<p>We are looking for...</p>"). This is a deliberately simple
    regex-based tag stripper — good enough for keyword matching, where
    we only care about the visible words, not proper HTML parsing.
    A production system handling untrusted HTML more seriously would
    use a real parser (e.g. BeautifulSoup) instead of a regex, since
    regexes are not a reliable way to parse arbitrary HTML in general
    — but for "strip tags before keyword-matching," this is fine.

    html.unescape() runs FIRST, before the tag-stripping regex - added
    2026-08-31 after two real bugs traced back to this being missing:
    (1) Barclays' raw Workday HTML spelled "C++" as "C&#43;&#43;" (the
    numeric HTML entity for "+") - the literal substring "c++" never
    appeared anywhere in the text, so the single most important
    Required skill for that posting was invisible to every keyword
    match, even though this package's own word-boundary regex was
    working exactly as designed. (2) A Rubrik posting's description
    came back with its OWN tags entity-encoded a level deep -
    "&lt;p&gt;...&lt;/p&gt;" instead of "<p>...</p>" - meaning
    _HTML_TAG_RE (which only matches literal "<...>") never stripped
    ANY of it; unescaping first turns that back into real "<p>" tags,
    which the existing tag-stripping regex then correctly removes.
    Confirmed live against both real postings before shipping this fix.
    """
    return _HTML_TAG_RE.sub(" ", html.unescape(text or ""))


# CONFIRMED LIVE 2026-09-06, testing against 50 real postings pulled
# from LinkedIn/Indeed (a job-source not seen before in this package's
# history - fetchers' ATS-direct sources never had this problem).
# Several came back with markdown-style backslash-escaping on special
# characters - "10\+ Years", ".NET\'s", "C\#" - most likely from
# whatever HTML-to-text conversion the source job board / scraping
# library does internally. Same CLASS of bug as the HTML-entity issue
# strip_html() above already fixed (a source encoding silently hiding
# the literal substring a keyword pattern is searching for) - here,
# "10\+ Years" doesn't match the years-requirement regex's literal "+"
# at all, which is exactly how a real 10-year-experience posting
# (Luxoft, Angular Developer - "Experience: 10\+ Years (Mandatory)")
# scored a completely uncapped 90/100: the single most disqualifying
# line in the whole posting was invisible to the regex. Stripping the
# escaping backslash off common markdown-special characters fixes this
# at the source, before any pattern in this package ever runs against
# the text.
_MARKDOWN_ESCAPE_RE = re.compile(r"\\([#\-&.+*_\[\]()~`>!])")


def _strip_markdown_escapes(text: str) -> str:
    return _MARKDOWN_ESCAPE_RE.sub(r"\1", text)


# SPELLED-OUT NUMBERS - CONFIRMED REAL, FOUND 2026-09-06 testing
# against 50 real LinkedIn/Indeed postings: "Five or more years of
# applied Python development experience" (a real posting, BV Teck)
# was completely invisible to the digit-only years-requirement regex -
# "five" is never going to match `\d+`. Fixed by normalizing spelled-
# out numbers to digits BEFORE that regex ever runs (see
# scoring/scorer.py's score_job()), rather than writing a second,
# parallel word-based years-regex and duplicating the whole gating
# logic for it. Capped at twelve - a JD spelling out "twenty years"
# instead of "20" essentially never happens in practice, and going
# further just risks matching an unrelated spelled-out number
# elsewhere in the text.
_SPELLED_NUMBER_TO_DIGIT = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}
_SPELLED_YEARS_RE = re.compile(
    r"\b(" + "|".join(_SPELLED_NUMBER_TO_DIGIT) + r")\b(?=\s*(?:or more\s*)?\+?\s*years?\b)",
    re.IGNORECASE,
)


def _normalize_spelled_years(text: str) -> str:
    return _SPELLED_YEARS_RE.sub(lambda m: _SPELLED_NUMBER_TO_DIGIT[m.group(1).lower()], text)
