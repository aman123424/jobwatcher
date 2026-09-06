"""fetchers/talentbrew.py - TalentBrew (Radancy), the CMS behind Optum/UHG's careers site."""

import re

from scoring import is_relevant_title

from .common import _merge_dedupe_by_job_id, _safe_get_text

_TALENTBREW_JOB_CARD_RE = re.compile(
    r'<a href="(?P<href>/job/[^"]+)" data-job-id="(?P<job_id>[^"]+)"[^>]*>\s*'
    r'<div>\s*<h2>\s*(?P<title>.*?)\s*</h2>\s*'
    r'<span class="job-id job-info">[^<]*</span>\s*'
    r'<span class="job-divider">[^<]*</span>\s*'
    r'<span class="job-location[^"]*">\s*(?P<location>.*?)\s*</span>',
    re.S,
)
_TALENTBREW_DESCRIPTION_RE = re.compile(
    r'ats-description ajd_job-details__ats-description">\s*<div class="jd-wrapper">(.*?)</div>\s*</section>',
    re.S,
)
_TALENTBREW_POSTED_DATE_RE = re.compile(r'"PostedDate":"([^"]+)"')


def fetch_talentbrew(display_name: str, config: str) -> list[dict]:
    """
    TalentBrew (Radancy) - a career-site CMS used by large employers,
    found while chasing Optum specifically (2026-09-05): Optum's parent
    UnitedHealth Group used to run public job search on native Oracle
    Taleo pages, but has since migrated that public-facing search to a
    TalentBrew-branded site (careers.unitedhealthgroup.com) - Taleo
    itself is still alive underneath, just for login/application-status
    now, not for public browsing. See PROJECT_LOG.md for the full
    investigation (including the dead-end Taleo REST attempt).

    NOT a JSON API - unlike every other fetcher in this package,
    TalentBrew renders its search results as plain server-side HTML (no
    separate XHR/REST call exists; confirmed live by inspecting network
    traffic thoroughly and finding nothing but the page navigation
    itself). So this scrapes that HTML directly with the two regexes
    above, the same "adapter" principle as every other fetch_* function
    here, just parsing HTML instead of JSON.

    URL SHAPE (confirmed live, several wrong guesses ruled out first):
        https://careers.unitedhealthgroup.com/search-jobs/{keyword}/{location}[/{page}]
            ?orgIds={org_id}&kt=1&alp={alp}&alt={alt}

    `kt=1` IS LOAD-BEARING, NOT A TRACKING PARAM - a first pass dropped
    it as looking like marketing noise (alongside a genuinely irrelevant
    `src=NGP-...` tracking tag) and every keyword silently returned the
    exact same unfiltered "292 results" (the site's total India-wide
    count) regardless of what keyword was searched. Restoring `kt=1`
    fixed it immediately (confirmed live: software=196, nurse=6,
    engineer=230, backend=35 - all distinct, all correct) - this is the
    param that tells the site to actually treat the path segment as a
    keyword filter rather than ignoring it.

    `alp`/`alt` are TalentBrew's own internal location-taxonomy IDs (not
    something to guess per-company) - `alp` for "India" specifically was
    confirmed live in this project (see config below); a different
    company/location on TalentBrew would need its own values found the
    same way (search the site's own UI, copy the resulting URL).

    ARGUMENT FORMAT: pipe-separated "org_id|location|alp|alt|keywords",
    e.g. "34088|India|1269750|2|software,backend,frontend,full stack".
    Same multi-keyword + merge-by-job_id de-dupe pattern as
    fetchers/pcsx.py and fetchers/amazon.py, and for the same reason -
    a single "software" search risks missing real titles like "Backend
    Developer" with no literal "software" in them.

    NO BRAND FILTER APPLIED HERE, DELIBERATELY: this URL already scopes
    to org_id=34088 (UnitedHealth Group's whole TalentBrew org, which
    includes Optum, UnitedHealthcare, and UHG corporate) + location=India.
    Confirmed live 2026-09-05 that EVERY India-tagged posting on this
    board carries Optum's own brand-facet class (the "India" location
    facet count and the "OptumIndia" brand facet count were IDENTICAL -
    292 both ways) - UHC/UHG-corporate have no India presence on this
    board at all, so filtering by brand here would be redundant
    complexity, not real narrowing.

    TWO-STEP PER JOB, SEQUENTIAL, SAME REASONING AS
    fetchers/pcsx.py's _enrich_pcsx_descriptions and fetchers/workday.py's
    _enrich_workday_descriptions: the search-results page only gives
    title/location, not the real description -
    _enrich_talentbrew_descriptions() below fetches each survivor's own
    detail page (one request at a time, same server, same rate-limit
    caution) for the real description HTML and a real ISO posted-date
    timestamp (confirmed live, embedded in the detail page's own
    analytics data blob: "PostedDate":"2026-09-04T20:44:26Z").

    PAGE 1 ONLY - NO REAL PAGINATION, CONFIRMED LIVE 2026-09-05: this
    keyword-filtered search route does NOT support jumping to page N
    directly. `data-total-pages="14"` genuinely appears on page 1's own
    response (looks like real pagination exists), but /search-jobs/
    {keyword}/{location}/2, /3, /4 ... all returned BYTE-FOR-BYTE
    IDENTICAL content to each other (verified: same 15 job_ids, same
    order, at page 2, 5, and 9) - stateless too (no session cookie ever
    gets set), so it's not a "need to click Next in-session" issue
    either. The real "next page" mechanism this site's own JS actually
    uses is undiscovered - would need a live browser trace of clicking
    the pagination control for real, not guessed URL shapes. A first
    version of this trusted data-total-pages as a stopping condition
    and looped through pages 2-14 anyway - each one duplicate content,
    silently discarded by the merge-by-job_id dedupe below, for zero
    benefit and 13x the requests. So: page 1 only, for now - real,
    correctly keyword-filtered, just capped at ~15 results per keyword.
    Combined with running one search per keyword (already necessary
    for coverage - see ARGUMENT FORMAT above) this still nets a
    reasonable spread rather than being stuck at 15 total.
    """
    parts = config.split("|")
    if len(parts) != 5:
        print(f"  [WARN] {display_name}: malformed talentbrew identifier "
              f"'{config}' (expected org_id|location|alp|alt|keywords) - skipping")
        return []
    org_id, location, alp, alt, keywords_raw = parts
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    def fetch_for_one_keyword(keyword: str) -> list[dict]:
        url = (
            f"https://careers.unitedhealthgroup.com/search-jobs/{keyword}/{location}"
            f"?orgIds={org_id}&kt=1&alp={alp}&alt={alt}"
        )
        html = _safe_get_text(url)
        if not html:
            return []

        return [
            {
                "source_company": display_name,
                "platform": "talentbrew",
                "job_id": card.group("job_id"),
                "title": card.group("title"),
                "location": card.group("location"),
                "url": f"https://careers.unitedhealthgroup.com{card.group('href')}",
                "updated_at": None,  # filled in by _enrich_talentbrew_descriptions below, for relevant titles only
                "raw_description": card.group("title"),  # placeholder until enriched, same convention as fetch_workday's list-only fields
            }
            for card in _TALENTBREW_JOB_CARD_RE.finditer(html)
        ]

    results_per_keyword = [fetch_for_one_keyword(keyword) for keyword in keywords]
    jobs = _merge_dedupe_by_job_id(results_per_keyword)

    _enrich_talentbrew_descriptions(jobs)
    return jobs


def _enrich_talentbrew_descriptions(jobs: list[dict]) -> None:
    """
    Same "in place" mutation, same is_relevant_title() pre-filter, and
    same DELIBERATELY SEQUENTIAL reasoning as fetchers/pcsx.py's
    _enrich_pcsx_descriptions and fetchers/workday.py's
    _enrich_workday_descriptions - one request at a time to this one
    server, only for jobs whose title already looks like a real
    Software Engineer role.
    """
    for job in jobs:
        if not is_relevant_title(job["title"]):
            continue
        html = _safe_get_text(job["url"])
        if not html:
            continue
        desc_match = _TALENTBREW_DESCRIPTION_RE.search(html)
        if desc_match:
            job["raw_description"] = desc_match.group(1)
        date_match = _TALENTBREW_POSTED_DATE_RE.search(html)
        if date_match:
            job["updated_at"] = date_match.group(1)
