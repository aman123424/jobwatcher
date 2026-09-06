"""fetchers/atlassian.py - Atlassian's own careers listing feed (backed by iCIMS)."""

from .common import _safe_get


def fetch_atlassian(display_name: str, _unused_config: str) -> list[dict]:
    """
    Atlassian's own careers listing feed - backed by iCIMS (their ATS
    vendor), but unlike the RippleHire/CornerStone iCIMS-style APIs
    flagged as blocked in NEEDS_MORE_INFO (companies.py), this one is a
    plain, unauthenticated GET that returns EVERY open role worldwide in
    a single response - no pagination, no per-job detail call needed,
    no bearer token. Confirmed live 2026-08-29: 233 total postings, 27
    India-related, full HTML description sections already included.

    URL: https://www.atlassian.com/endpoint/careers/listings

    _unused_config exists only so this function's signature matches
    every other fetch_* function in this package (display_name,
    config) - the FETCHERS dispatch in main.py always calls whichever
    function it looks up with exactly those two arguments (see
    companies.py's module docstring for how each company's tuple gets
    unpacked into them), and this is the one platform that genuinely
    needs no per-company identifier at all: there's nothing to filter
    by or parameterize, the URL is always the same no matter which
    company row in companies.py points at it. A NOTE FOR IF THIS EVER
    STOPS BEING TRUE (a second Atlassian-style company shows up
    needing this same pattern): this URL would need to become
    configurable via that argument instead, the same way every other
    platform's config string already works.

    NO LOCATION FILTER AT THE API LEVEL - unlike Amazon/pcsx, which
    accept a country/location query param, this endpoint has none: you
    get the whole company's global job list every call, and India-only
    filtering happens the same place it does for Greenhouse/Lever/Ashby
    (main.py's is_india_location() check on the returned "location"
    string, after fetching) rather than as a server-side narrowing.
    Fine in practice - only 233 total roles, nowhere near a volume that
    needs trimming before it's even fetched.

    FULL DESCRIPTIONS INCLUDED FOR FREE - unlike Workday/
    SmartRecruiters/pcsx, which only give a title in their list/search
    response and need a separate per-job detail request for real
    description text (see fetchers/workday.py's _enrich_workday_descriptions()
    etc.), this endpoint's single response already carries real HTML
    description content for every job. `overview` is deliberately left
    OUT of the combined raw_description below - like Atlassian's own
    "Working at Atlassian..." boilerplate paragraph visible in a sample
    response, it's about the COMPANY, not the specific role, and would
    only dilute keyword matching (same reasoning
    _enrich_smartrecruiters_descriptions() already applies to dropping
    SmartRecruiters' companyDescription section). responsibilities and
    qualifications are kept - qualifications especially is exactly
    where JD-importance detection (scoring package) finds real
    "Required"/"Preferred" structure.

    LOCATIONS IS A LIST, NOT ONE STRING - e.g.
    ["Bengaluru - India -   Bengaluru,  560071 India", "Remote - Remote"]
    - a role can be listed as open in several offices/remote options at
    once. Joined with "; " (not ", ", since individual entries already
    contain commas of their own - using the same separator would make
    the joined result ambiguous to read).
    """
    data = _safe_get("https://www.atlassian.com/endpoint/careers/listings")
    if not data or not isinstance(data, list):
        return []

    jobs = []
    for j in data:
        locations = j.get("locations") or []
        description_parts = [j.get("responsibilities", ""), j.get("qualifications", "")]
        jobs.append({
            "source_company": display_name,
            "platform": "atlassian",
            "job_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "location": "; ".join(locations),
            "url": j.get("applyUrl", ""),
            "updated_at": (j.get("portalJobPost") or {}).get("updatedDate"),
            "raw_description": " ".join(part for part in description_parts if part),
        })
    return jobs
