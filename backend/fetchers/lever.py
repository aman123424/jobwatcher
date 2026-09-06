"""fetchers/lever.py - Lever's public Postings API."""

from datetime import datetime, timezone

from .common import _safe_get


def fetch_lever(display_name: str, slug: str) -> list[dict]:
    """
    Lever's public Postings API.

    URL shape:
        https://api.lever.co/v0/postings/{slug}?mode=json

    Lever returns a flat JSON array directly (not wrapped in an object
    like Greenhouse does) — one more reason we normalize everything
    into the same shape before it goes anywhere else in the program.
    """
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = _safe_get(url)
    if not data:
        return []

    jobs = []
    for j in data:
        jobs.append({
            "source_company": display_name,
            "platform": "lever",
            "job_id": j.get("id", ""),
            "title": j.get("text", ""),  # Lever calls the job title "text"
            "location": (j.get("categories") or {}).get("location", ""),
            "url": j.get("hostedUrl", ""),
            # Lever gives a Unix timestamp in milliseconds, not an ISO
            # string like Greenhouse — we convert it here so that by
            # the time this data leaves the fetchers package, EVERY
            # platform's "updated_at" looks the same (an ISO 8601 string).
            "updated_at": _lever_ms_to_iso(j.get("createdAt")),
            "raw_description": (j.get("descriptionPlain") or j.get("description") or ""),
        })
    return jobs


def _lever_ms_to_iso(ms):
    """Convert Lever's millisecond Unix timestamp to an ISO string."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None
