"""fetchers/deshaw.py - D. E. Shaw's Next.js-rendered careers page."""

import re

from .common import _safe_get, _safe_get_text

_NEXT_BUILD_ID_RE = re.compile(r'"buildId":"([^"]+)"')


def fetch_deshaw(display_name: str, base_domain: str) -> list[dict]:
    """
    D. E. Shaw's careers page is server-rendered by Next.js, and its
    full job list — title, location, full description HTML — is
    embedded directly in the page's own SSR data payload. There's no
    separate ATS API to call; the "API" IS the page's own data source.

    TWO-STEP FETCH, because that data lives behind a build-specific URL:
      1. GET the real careers page and pull Next.js's current "buildId"
         out of the embedded __NEXT_DATA__ script tag. This ID changes
         every time D. E. Shaw redeploys the site, so it can't be
         hardcoded — has to be read fresh each run, same principle as
         Walmart/Rippling's identical Next.js pattern (checked but not
         pursued further for those two — see PROJECT_LOG for why).
      2. GET /_next/data/{buildId}/en/careers.json, which returns
         exactly what the page itself renders from.

    Confirmed live end-to-end on 2026-08-26: buildId extraction, the
    resulting careers.json fetch, and the job-detail URL pattern
    (/careers/open-positions/{jobUrl}) all verified against real
    responses. 75 open roles recovered in one response at last check —
    small enough that no pagination logic was needed; if that ever
    changes, this will need revisiting (the response gave no visible
    "total" or paging field to test against).
    """
    html = _safe_get_text(f"https://www.{base_domain}/careers/open-positions")
    if not html:
        return []

    match = _NEXT_BUILD_ID_RE.search(html)
    if not match:
        print(f"  [WARN] {display_name}: couldn't find Next.js buildId on the "
              f"careers page - site structure may have changed")
        return []
    build_id = match.group(1)

    data = _safe_get(f"https://www.{base_domain}/_next/data/{build_id}/en/careers.json")
    if not data or not isinstance(data, dict):
        return []

    regular_jobs = ((data.get("pageProps") or {}).get("regularJobs")) or []

    jobs = []
    for entry in regular_jobs:
        d = entry.get("data", {})
        locations = (d.get("jobMetadata") or {}).get("jobLocations") or []
        job_url = d.get("jobUrl", "")
        jobs.append({
            "source_company": display_name,
            "platform": "deshaw",
            "job_id": str(d.get("id", "")),
            "title": d.get("displayName", ""),
            "location": ", ".join(loc.get("name", "") for loc in locations),
            "url": f"https://www.{base_domain}/careers/open-positions/{job_url}" if job_url else "",
            "updated_at": None,  # not present anywhere in this response shape
            "raw_description": (d.get("jobDescription") or {}).get("websiteDescription", ""),
        })

    return jobs
