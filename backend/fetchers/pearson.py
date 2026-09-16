"""fetchers/pearson.py - Pearson's career site, backed by NLx/DirectEmployers' jobsyn.org search API (custom, single-company for now)."""

import re

import requests

from .common import SESSION, TIMEOUT, record_fetch_failure

SEARCH_URL = "https://prod-search-api.jobsyn.org/api/v1/solr/search"
ORIGIN = "pearson.jobs"
# Fixed by the API itself, NOT configurable - confirmed live that
# `num_items=100` in the query string is silently ignored, every
# response still comes back exactly 15 items/page regardless. Real
# pagination is the only way to get everything - see the `page` loop
# below.
PAGE_SIZE = 15


def fetch_pearson(display_name: str, _unused_config: str) -> list[dict]:
    """
    Pearson's real careers.jobs site (pearson.jobs) doesn't run its own
    search backend - it calls out to prod-search-api.jobsyn.org, which
    is NLx/DirectEmployers' infrastructure (confirmed by the
    "federal_contractor" field on every posting, and NLx's own stated
    purpose - a federal-contractor job-posting compliance network with
    900+ member companies, per directemployers.org).

    FILED AS A ONE-OFF CUSTOM FETCHER, NOT A NEW TIER - unlike Oracle
    Cloud/Zoho Recruit/pcsx, this was NOT confirmed reusable across
    other companies. Tried live: several other real DirectEmployers-
    affiliated companies' likely domains (AT&T, IHG, Hilton,
    ConocoPhillips, IBM, Johnson & Johnson - multiple domain-format
    guesses each) as the `x-origin` header value below - every single
    one 404'd. DirectEmployers runs more than one product, and this
    specific jobsyn.org backend evidently isn't shared by all of them,
    or requires an origin value that isn't simply guessable from a
    company's own domain. If a second real company is ever confirmed
    live on this exact backend, THAT is the moment to generalize this
    into a real per-company config string (Aman's own explicit call,
    2026-09-16) - not before, on a guess.

    _unused_config exists only so this function's signature matches
    every other fetch_* function (display_name, config) - same "no
    per-company identifier needed (yet)" reasoning as fetch_atlassian's
    own docstring.

    AUTH: none needed, but a REQUIRED HTTP HEADER, not just query
    params - confirmed live that a request with no `x-origin` header
    gets a clean 400 ({"errors":{"origin":"The origin is required."}}).
    This is the first fetcher in this package that needs a custom
    header rather than everything being expressible in the URL/query
    string alone.

    LOCATION SCOPED SERVER-SIDE (`location=ind`) - same reasoning
    fetch_amazon already gives for its own country-scoped API call:
    Pearson is large enough globally that fetching every location and
    filtering down to India afterward (the Greenhouse/Lever/Ashby way)
    would be real wasted work when the API itself can narrow it first.

    NO EARLY-STOP ON STALENESS - deliberately, unlike Workday/Oracle
    Cloud/Goldman Sachs. Total volume here is small (100 India postings
    across 7 pages, confirmed live) - nowhere near the scale that made
    early-stop worth the complexity for those other platforms - and
    page-to-page date ordering was never rigorously confirmed
    monotonic here, unlike those platforms' own explicit `sortBy=
    POSTING_DATES_DESC`-style parameters. Simplest safe choice: always
    fetch every page, bounded only by the response's own
    `pagination.total_pages` (plus a safety cap, same reasoning every
    other paginated fetcher here already has one).

    FULL DESCRIPTIONS INCLUDED FOR FREE, same as fetch_atlassian - no
    separate per-job detail call needed, `description` in the list
    response is already the real, full job text (confirmed live,
    several thousand characters on a real posting).

    NO DIRECT APPLY-URL FIELD IN THE API RESPONSE - had to construct
    it, and confirmed the constructed URL is actually correct (not
    just a 200 that silently 404s client-side - Pearson's site is a
    JS SPA, so a WRONG url/guid combination still returns HTTP 200 with
    an empty shell; only checking the REAL RENDERED page confirms
    correctness). Pattern, confirmed live on two different real jobs
    in two different cities:
        https://pearson.jobs/{city}-{country}/{title_slug}/{guid}/job/
    where {city}-{country} is a lowercased, hyphenated slug built from
    city_exact + country_short_exact (e.g. "noida-ind", "chennai-ind")
    - _location_slug() below builds this the same way, generalized to
    handle multi-word city names (not seen in testing, but a real
    possibility) rather than just the two single-word cities actually
    tested.
    """
    jobs = []
    page = 1

    while True:
        try:
            resp = SESSION.get(
                SEARCH_URL,
                params={"page": page, "location": "ind", "num_items": PAGE_SIZE},
                headers={"x-origin": ORIGIN, "Accept": "application/json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {SEARCH_URL} (page={page}): {e}")
            record_fetch_failure(str(e))
            break
        except ValueError as e:
            print(f"  [WARN] bad JSON from {SEARCH_URL} (page={page}): {e}")
            record_fetch_failure(str(e))
            break

        if not isinstance(data, dict) or "jobs" not in data:
            print(f"  [WARN] unexpected response shape from {SEARCH_URL} (page={page}): {data}")
            record_fetch_failure(f"unexpected response shape from {SEARCH_URL}")
            break

        postings = data.get("jobs") or []
        if not postings:
            break

        for p in postings:
            guid = p.get("guid", "")
            location_slug = _location_slug(p.get("city_exact"), p.get("country_short_exact"))
            jobs.append({
                "source_company": display_name,
                "platform": "pearson",
                "job_id": guid,
                "title": p.get("title_exact", ""),
                "location": p.get("location_exact", ""),
                "url": f"https://{ORIGIN}/{location_slug}/{p.get('title_slug', '')}/{guid}/job/",
                # date_added, not date_updated - the same "when was
                # this genuinely POSTED, not last touched" distinction
                # every other platform's updated_at already follows.
                # A real ISO 8601 instant with milliseconds - no new
                # job_dates.py branch needed, the generic fallback
                # branch there already parses this correctly.
                "updated_at": p.get("date_added"),
                "raw_description": p.get("description") or p.get("title_exact", ""),
            })

        pagination = data.get("pagination") or {}
        total_pages = pagination.get("total_pages", page)
        if page >= total_pages:
            break
        page += 1
        if page > 20:  # safety cap - same reasoning every other paginated fetcher here has one
            print(f"  [WARN] {display_name}: stopped after 20 pages (safety cap)")
            break

    return jobs


def _location_slug(city: str | None, country_short: str | None) -> str:
    """
    Builds the "{city}-{country}" URL segment fetch_pearson() needs -
    e.g. "noida-ind", "chennai-ind" - confirmed live for those two
    single-word cities. Lowercases and replaces anything that isn't a
    letter/digit with a single hyphen, so a multi-word city (untested,
    but plausible - "New Delhi" -> "new-delhi") degrades sensibly
    instead of producing a URL with raw spaces in it.
    """
    parts = [p for p in (city, country_short) if p]
    slug = "-".join(parts)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-")
    return slug.lower()
