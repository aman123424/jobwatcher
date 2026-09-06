"""fetchers/ashby.py - Ashby's public Job Board API."""

from .common import _safe_get


def fetch_ashby(display_name: str, slug: str) -> list[dict]:
    """
    Ashby's public Job Board API.

    URL shape:
        https://api.ashbyhq.com/posting-api/job-board/{slug}

    Ashby wraps its list under a "jobs" key too, like Greenhouse, but
    the individual field names are different again (this is the whole
    reason normalization exists — every platform is "almost" the same
    shape but never quite identical).
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _safe_get(url)
    if not data:
        return []

    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "source_company": display_name,
            "platform": "ashby",
            "job_id": j.get("id", ""),
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "url": j.get("jobUrl", ""),
            "updated_at": j.get("publishedAt"),
            "raw_description": j.get("descriptionPlain", ""),
        })
    return jobs
