"""fetchers/greenhouse.py - Greenhouse's public Job Board API."""

from .common import _safe_get

# Some companies run a custom career-site FRONTEND that pulls its data
# from Greenhouse's API but does its OWN internal ID assignment for
# each posting - meaning Greenhouse's own "absolute_url" field points
# to a URL using GREENHOUSE's job id, which that company's frontend
# doesn't actually recognize (it silently falls back to a generic
# listing page instead of the specific job). Confirmed live 2026-08-28
# for SquarePoint specifically: their site's own internal job IDs (read
# straight off their real "Apply" links, e.g. .../opportunity-details
# ?id=6040910) share NO overlap at all with Greenhouse's ids for the
# same postings, and there's no plain HTTP-fetchable API to resolve one
# to the other - the mapping only exists inside their client-side JS,
# which would need a full browser render (not practical to do on every
# fetch) to resolve. Rather than link to a URL that LOOKS specific but
# silently lands on the wrong page, these slugs fall back to the real,
# working listing page - honest about not being able to deep-link,
# instead of confidently wrong.
_BROKEN_ABSOLUTE_URL_FALLBACKS = {
    "squarepointcapital": "https://www.squarepoint-capital.com/open-opportunities",
}


def fetch_greenhouse(display_name: str, slug: str) -> list[dict]:
    """
    Greenhouse's public Job Board API.
    Docs (unofficial but stable/widely used): one GET request, no auth.

    URL shape:
        https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

    `content=true` asks Greenhouse to include the full job description
    HTML in the response too — we want this because scoring.py needs
    the description text, not just the title, to judge a real match.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = _safe_get(url)
    if not data:
        return []

    # See _BROKEN_ABSOLUTE_URL_FALLBACKS above - None for every slug
    # except the handful confirmed to need this workaround.
    url_fallback = _BROKEN_ABSOLUTE_URL_FALLBACKS.get(slug)

    jobs = []
    # Greenhouse's response shape is: {"jobs": [ {...}, {...} ], "meta": {...}}
    for j in data.get("jobs", []):
        jobs.append({
            "source_company": display_name,
            "platform": "greenhouse",
            "job_id": str(j.get("id")),
            "title": j.get("title", ""),
            # location is a nested object: {"name": "Bengaluru, India"}
            "location": (j.get("location") or {}).get("name", ""),
            "url": url_fallback or j.get("absolute_url", ""),
            "updated_at": j.get("updated_at"),  # already ISO 8601
            "raw_description": j.get("content", ""),  # HTML, stripped later
        })
    return jobs


if __name__ == "__main__":
    # Quick manual test: run `python -m fetchers.greenhouse` to sanity-
    # check one known-good company end to end, without running the
    # whole system.
    test_jobs = fetch_greenhouse("Razorpay", "razorpaysoftwareprivatelimited")
    print(f"Fetched {len(test_jobs)} jobs from Razorpay's Greenhouse board.")
    if test_jobs:
        print("Sample job:")
        sample = test_jobs[0]
        for k, v in sample.items():
            preview = (v[:80] + "...") if isinstance(v, str) and len(v) > 80 else v
            print(f"  {k}: {preview}")
