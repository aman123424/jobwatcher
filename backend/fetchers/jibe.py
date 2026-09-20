"""fetchers/jibe.py - iCIMS Jibe careers-home public jobs API (Tier 1-shaped, reusable across companies)."""

import requests

from .common import SESSION, TIMEOUT, record_fetch_failure

PAGE_SIZE = 100
MAX_PAGES = 30


def fetch_jibe(display_name: str, host: str) -> list[dict]:
    """
    iCIMS Jibe powers the "careers-home" Angular sites (recognizable by
    `data-jibe-search-version` in the page HTML). Found on Docusign
    (careers.docusign.com), then confirmed live on a second, unrelated
    company - Schneider Electric (careers.se.com) - with the identical
    response shape, so this is a real reusable tier.

    KNOWN BLOCKER, Schneider: careers.se.com's firewall returns 403 to
    this project's custom User-Agent ("jobwatch/0.1 (... contact: ...)"),
    while a generic UA (or Docusign, with ours) gets 200 - isolated
    live; Accept-Encoding and other headers are not the cause. Not
    worked around, since the honest UA is a deliberate project choice.

    ARGUMENT FORMAT: `host` is the bare careers hostname, e.g.
    "careers.docusign.com" - same simple shape as fetch_zoho_recruit.

    AUTH: none. GET {host}/api/jobs?page=N&limit=100&country=India.
    `limit` is capped at 100 (500 returns an error with no `jobs`
    key). `country=India` filters server-side (Docusign: 19 of 253,
    all IN). Pagination stops at the response's own `totalCount`.
    country_code is deliberately NOT re-filtered here: a multi-location
    posting can have a non-IN primary country while listing India, and
    the pipeline's own India filter already handles that on full_location.

    PUBLIC URL: `https://{host}/careers-home/jobs/{slug}`, verified in a
    real browser on both companies (the SPA renders the real job title).
    The API's own `apply_url` is a separate iCIMS login page, so it isn't used.

    DATES: Docusign's `posted_date` is ISO 8601 ("2026-09-18T04:56:00+0000").
    Schneider's is a plain "September 17, 2026" string, which job_dates.py's
    generic ISO branch can't parse - for those, `create_date` (ISO on both
    tenants) is used instead, so no new job_dates.py branch is needed.

    FULL DESCRIPTIONS are included in the list response (HTML fragments,
    same as other platforms here) - no detail call needed.
    """
    host = host.strip()
    list_url = f"https://{host}/api/jobs"
    jobs = []
    page = 1

    while True:
        try:
            resp = SESSION.get(
                list_url,
                params={"page": page, "limit": PAGE_SIZE, "country": "India"},
                headers={"Accept": "application/json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {list_url} (page={page}): {e}")
            record_fetch_failure(str(e))
            break
        except ValueError as e:
            print(f"  [WARN] bad JSON from {list_url} (page={page}): {e}")
            record_fetch_failure(str(e))
            break

        if not isinstance(data, dict) or "jobs" not in data:
            print(f"  [WARN] unexpected response shape from {list_url} (page={page}): {data}")
            record_fetch_failure(f"unexpected response shape from {list_url}")
            break

        postings = data.get("jobs") or []
        if not postings:
            break

        for wrapper in postings:
            p = wrapper.get("data") or {}
            slug = p.get("slug") or p.get("req_id")
            posted = p.get("posted_date") or ""
            updated_at = posted if "T" in posted else p.get("create_date")
            jobs.append({
                "source_company": display_name,
                "platform": "jibe",
                "job_id": str(p.get("req_id") or slug),
                "title": p.get("title", ""),
                "location": p.get("full_location") or p.get("location_name", ""),
                "url": f"https://{host}/careers-home/jobs/{slug}",
                "updated_at": updated_at,
                "raw_description": p.get("description") or p.get("title", ""),
            })

        if len(jobs) >= (data.get("totalCount") or 0):
            break
        page += 1
        if page > MAX_PAGES:
            print(f"  [WARN] {display_name}: stopped after {MAX_PAGES} pages (safety cap)")
            break

    return jobs
