"""fetchers/goldman_sachs.py - Goldman Sachs' own "Higher" careers platform (custom, single-company)."""

from datetime import datetime, timedelta, timezone

import requests

from scoring import is_relevant_title

from .common import FRESHNESS_WINDOW_DAYS, SESSION, TIMEOUT, record_fetch_failure

GRAPHQL_URL = "https://api-higher.gs.com/gateway/api/v1/graphql"
PAGE_SIZE = 25

# The four values roleSearchExperiences (a real query on this API)
# returns. INTERNAL_MOBILITY deliberately excluded - confirmed by the
# name alone and consistent with it being for existing GS employees
# moving teams internally, not something an external candidate could
# ever apply to; including it would just add noise no one here can act on.
_EXPERIENCES = ["PROFESSIONAL", "EARLY_CAREER", "CAMPUS"]

_LIST_QUERY = """
query($input: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $input) {
    items {
      roleId
      jobTitle
      lastPostedDate
      locations { city state country primary }
    }
  }
}
"""

_DETAIL_QUERY = """
query($id: String!) {
  role(externalSourceId: $id, externalSourceFetch: true) {
    descriptionHtml
  }
}
"""


def fetch_goldman_sachs(display_name: str, _unused_config: str) -> list[dict]:
    """
    Goldman Sachs' own in-house "Higher" recruiting platform
    (higher.gs.com) - a real, documented-by-introspection GraphQL API
    on their own domain, not a third-party ATS vendor another company
    could also be running. This is why it lives here as a one-off
    custom fetcher (same shape as fetch_atlassian/fetch_pcsx/
    fetch_amazon), not a new Tier - see the conversation this was
    researched in for the "custom vs. reusable platform" reasoning.

    STATUS: live-tested and working, found via GraphQL introspection
    (confirmed enabled on this endpoint - not a reverse-engineered
    guess). 997+ total roles across PROFESSIONAL/EARLY_CAREER/CAMPUS,
    real India postings confirmed (e.g. a Bengaluru "Software
    Engineering" role, live-tested 2026-09-12).

    _unused_config exists only so this function's signature matches
    every other fetch_* function (display_name, config) - see
    fetch_atlassian's own docstring for the full reasoning; this is
    the same "no per-company identifier needed" case.

    QUERY SHAPE: found entirely through GraphQL introspection
    (`{ __schema { ... } }` and `{ __type(name: "...") { ... } }`
    queries against this same endpoint) - roleSearch takes a
    RoleSearchQueryInput with page {pageSize, pageNumber}, a REQUIRED
    experiences list (an empty/missing one 400s), and an optional
    sort. No keyword/searchTerm filter is sent - same reasoning every
    other fetcher gives for an "empty search": is_relevant_title()
    (ingest.py) already filters centrally, and we want every open role
    Software-Engineer-shaped or not, so scoring/filtering never misses
    one this fetcher pre-filtered away.

    EARLY STOP ON STALENESS: `sort: {sortStrategy: POSTED_DATE,
    sortOrder: DESC}` - confirmed live sorted genuinely newest-first
    (page 0 was all "2026-09-11"; page 20 had shifted to "2026-09-09"
    on the same query). `lastPostedDate` is a real ISO 8601 instant
    with time-of-day (unlike Workday's day-only relative labels) - no
    special job_dates.py helper needed, it's parsed directly below,
    and downstream code (job_dates.py's parse_posted_datetime) already
    handles a genuine ISO string via its generic fallback branch
    without needing a "goldman_sachs" platform special-case.

    PER-JOB DETAIL CALL FOR FULL DESCRIPTIONS: the list query's items
    don't carry a usable description (`shortDescription` is close to
    empty - confirmed live, e.g. just "Risk " for an actual posting) -
    a separate `role(externalSourceId, externalSourceFetch: true)`
    query returns `descriptionHtml` with real, substantial HTML
    (6,159 chars confirmed on a real Bengaluru posting). Same
    "externalSourceId must be the NUMERIC prefix of roleId, not the
    full string" gotcha is why job_id below is split on "_" - passing
    the full roleId (e.g. "183895_GS_MID_CAREER") 400s with "must
    match \\"\\\\d+\\"". That same numeric id is also what
    higher.gs.com/roles/{id} (the public apply URL) expects - both
    confirmed live.

    Same "only enrich jobs whose title already looks relevant" filter
    every other enrichment step in this package uses (see
    fetch_workday's own docstring) - one request per relevant job, not
    every job up front.
    """
    jobs = []
    page_number = 0

    while True:
        variables = {
            "input": {
                "page": {"pageSize": PAGE_SIZE, "pageNumber": page_number},
                "experiences": _EXPERIENCES,
                "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
            }
        }
        try:
            resp = SESSION.post(
                GRAPHQL_URL,
                json={"query": _LIST_QUERY, "variables": variables},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {GRAPHQL_URL} (page={page_number}): {e}")
            record_fetch_failure(str(e))
            break
        except ValueError as e:
            print(f"  [WARN] bad JSON from {GRAPHQL_URL} (page={page_number}): {e}")
            record_fetch_failure(str(e))
            break

        if not isinstance(data, dict) or data.get("errors"):
            print(f"  [WARN] GraphQL error from {GRAPHQL_URL} (page={page_number}): {data.get('errors') if isinstance(data, dict) else data}")
            record_fetch_failure(f"GraphQL error at page {page_number}")
            break

        items = ((data.get("data") or {}).get("roleSearch") or {}).get("items") or []
        if not items:
            break

        page_has_recent_job = False
        for item in items:
            posted_at = item.get("lastPostedDate")
            days_old = _days_old(posted_at)
            # None (unparseable/missing) treated as recent - same
            # "never stop early on a guess" reasoning every other
            # early-stop fetcher in this package already follows.
            is_recent = days_old is None or days_old < FRESHNESS_WINDOW_DAYS
            if is_recent:
                page_has_recent_job = True
            else:
                continue

            role_id = item.get("roleId") or ""
            numeric_id = role_id.split("_")[0]
            primary_location = next(
                (loc for loc in item.get("locations") or [] if loc.get("primary")),
                (item.get("locations") or [None])[0],
            ) or {}
            location = ", ".join(
                part for part in (primary_location.get("city"), primary_location.get("state"), primary_location.get("country")) if part
            )

            jobs.append({
                "source_company": display_name,
                "platform": "goldman_sachs",
                "job_id": numeric_id,
                "title": item.get("jobTitle", ""),
                "location": location,
                "url": f"https://higher.gs.com/roles/{numeric_id}",
                "updated_at": posted_at,
                # Placeholder until _enrich_goldman_sachs_descriptions
                # below replaces it - shortDescription (the only other
                # option in the list response) is near-empty, title is
                # the better placeholder, same choice fetch_workday
                # makes for the same reason.
                "raw_description": item.get("jobTitle", ""),
            })

        if len(items) < PAGE_SIZE:
            break
        if not page_has_recent_job:
            break

        page_number += 1
        if page_number * PAGE_SIZE > 2000:  # safety cap - same as every other paginated fetcher here
            print(f"  [WARN] {display_name}: stopped after 2000 jobs (safety cap)")
            break

    _enrich_goldman_sachs_descriptions(jobs)
    return jobs


def _days_old(posted_at: str | None) -> int | None:
    """lastPostedDate is a real ISO 8601 instant (e.g. "2026-09-11T19:10:39.760Z") - parsed directly here since it's only ever used for THIS fetcher's own early-stop pagination decision, not shared with job_dates.py's parse_posted_datetime (which handles it fine on its own via the generic ISO fallback branch - see this module's own docstring)."""
    if not posted_at:
        return None
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - posted).days, 0)


def _enrich_goldman_sachs_descriptions(jobs: list[dict]) -> None:
    """Same in-place mutation, same sequential-not-concurrent, same is_relevant_title() pre-filter as every other enrichment step in this package (see fetch_workday's _enrich_workday_descriptions)."""
    for job in jobs:
        if not is_relevant_title(job["title"]):
            continue
        try:
            resp = SESSION.post(
                GRAPHQL_URL,
                json={"query": _DETAIL_QUERY, "variables": {"id": job["job_id"]}},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {GRAPHQL_URL} (job {job['job_id']}): {e}")
            record_fetch_failure(str(e))
            continue
        except ValueError as e:
            print(f"  [WARN] bad JSON from {GRAPHQL_URL} (job {job['job_id']}): {e}")
            record_fetch_failure(str(e))
            continue

        if not isinstance(data, dict) or data.get("errors"):
            continue

        role = (data.get("data") or {}).get("role")
        description = (role or {}).get("descriptionHtml")
        if description:
            job["raw_description"] = description
