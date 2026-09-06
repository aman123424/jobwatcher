"""fetchers/amazon.py - Amazon's own jobs-search JSON API."""

from datetime import datetime, timedelta, timezone

from .common import FRESHNESS_WINDOW_DAYS, _merge_dedupe_by_job_id, _safe_get


def fetch_amazon(display_name: str, country_base_query: str) -> list[dict]:
    """
    Amazon's own jobs-search JSON API — the exact same endpoint
    amazon.jobs' own frontend calls. Confirmed live via direct request
    on 2026-08-26: clean GET, no auth, real field names verified against
    an actual response (id_icims, title, normalized_location, job_path,
    posted_date, description_short) — same reliability tier as
    Greenhouse/Lever/Ashby despite Amazon being a "Custom Career Site"
    entry in the company list.

    URL shape:
        https://www.amazon.jobs/en/search.json
            ?offset={n}&result_limit=100&country={ISO3}&base_query={keyword}

    ARGUMENT FORMAT: pipe-separated "country|base_queries", e.g.
      "IND|software,backend,frontend,full stack".
      - country is an ISO3 code (IND, USA, ...) - THIS is the field that
        actually filters. `loc_query` (used in the first version of this
        fetcher) looked like it worked because "hits" stayed in a
        plausible range either way, but a live run on 2026-08-26 showed
        real non-India jobs (Sydney, San Francisco, Haifa) coming back
        with loc_query=India set - it's a relevance HINT, not a filter,
        and silently does nothing. Confirmed the real fix live: only
        `country=IND` (or `normalized_country_code[]=IND`) actually
        narrows results - IND-only hits dropped from 2,099 to 328 for
        "software engineer", and every sample result was genuinely IND.
      - base_queries is a COMMA-separated list of keywords, same reason
        and same merge-by-job_id de-dupe as fetch_pcsx (a single
        "software engineer" keyword risks missing "Backend Developer"-
        style titles with no literal "software" in them).

    "hits" is Amazon's own reported total, confirmed accurate against
    the real (now properly country-filtered) result count.

    EARLY STOP ON STALENESS (added 2026-08-26): switched `sort` from
    "relevant" to "recent" - confirmed live this returns results in
    real (if only day-granular, not exact-time) descending date order,
    unlike "relevant" which is scattered across many months. Once a
    full page's posted_date values are all older than
    FRESHNESS_WINDOW_DAYS, stop - later pages are guaranteed even
    older. Day-granularity (not hour) is exactly why
    FRESHNESS_WINDOW_DAYS uses a 2-day buffer rather than 1: two jobs
    posted hours apart near a day boundary can still show the same
    calendar date, so treating "yesterday" as still worth fetching
    is the safe direction to round.
    """
    # Same splitting pattern as fetch_pcsx: "IND|software,backend"
    # becomes parts = ["IND", "software,backend"].
    parts = country_base_query.split("|")
    country = parts[0] if len(parts) > 0 else ""
    # Same list-comprehension pattern as fetch_pcsx's `queries`: turn
    # "software,backend,frontend" into ["software", "backend", "frontend"].
    base_queries = [q.strip() for q in parts[1].split(",")] if len(parts) > 1 and parts[1] else [""]

    # The cutoff date used for the early-stop check below: "today minus
    # FRESHNESS_WINDOW_DAYS days". `.date()` on the end throws away the
    # time-of-day part, keeping just the calendar date - Amazon's
    # posted_date field is day-only ("August 25, 2026", no time), so
    # comparing full timestamps here would be comparing precision we
    # don't actually have.
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS)).date()

    def fetch_for_one_query(base_query):
        """
        Inner function (see fetch_pcsx for what that means) that does
        the full page-by-page fetch, INCLUDING the early-stop check,
        for exactly ONE keyword. Called once per keyword in
        base_queries below. Directly uses this outer function's
        `country` and `cutoff_date` without needing them passed in.
        """
        jobs_for_this_query = []
        offset = 0
        page_size = 100

        while True:
            url = (
                "https://www.amazon.jobs/en/search.json"
                f"?offset={offset}&result_limit={page_size}&sort=recent"
                f"&country={country}&base_query={base_query}"
            )
            data = _safe_get(url)
            if not data or not isinstance(data, dict):
                break

            job_list = data.get("jobs", [])
            if not job_list:
                break

            # We only want to keep paging (fetching the NEXT page) if
            # this page still has at least one job recent enough to
            # matter. Starts False; flipped True below the moment we
            # find one such job anywhere on this page.
            page_has_recent_job = False
            for j in job_list:
                job_id = str(j.get("id_icims", ""))
                job_path = j.get("job_path", "")
                posted_date = j.get("posted_date")  # human string e.g. "April 9, 2026", not ISO

                # Turn Amazon's "August 25, 2026" text into an actual
                # Python date we can compare against cutoff_date.
                # strptime = "STRing Parse TIME": %B is the full month
                # name, %d the day number, %Y the 4-digit year - those
                # three codes together match Amazon's exact format.
                # Wrapped in try/except because a date we can't parse
                # shouldn't crash the whole fetch - we just treat it as
                # "unknown" (job_date = None) and move on.
                try:
                    job_date = datetime.strptime(posted_date, "%B %d, %Y").date() if posted_date else None
                except ValueError:
                    job_date = None  # unparseable - don't let it affect the stop decision either way

                if job_date is None or job_date >= cutoff_date:
                    page_has_recent_job = True

                # FIX (2026-08-31): this used to be
                # `j.get("description_short") or j.get("description", "")`
                # - "description_short" is a real field (not empty), so
                # `or` always picked it FIRST, and the actual full
                # description (confirmed live: ~6,000 chars, vs.
                # description_short's ~200-char marketing teaser) never
                # got used at all. Every Amazon job was being scored
                # against an intro paragraph with zero real requirements
                # text in it - confirmed as the direct cause of every
                # single Amazon job scoring close to 0 regardless of fit.
                # Fixed by using the real "description" field, PLUS
                # Amazon's own separate "basic_qualifications" and
                # "preferred_qualifications" fields (confirmed live to
                # hold real Required/Preferred content) - prefixed with
                # literal header text so scoring's own JD-importance
                # section detection (_REQUIRED_SECTION_RE /
                # _PREFERRED_SECTION_RE) correctly recognizes and weighs
                # them, the same way it already does for every other
                # platform's real Required/Preferred sections.
                description_parts = [j.get("description", "")]
                if j.get("basic_qualifications"):
                    description_parts.append("Required Qualifications: " + j["basic_qualifications"])
                if j.get("preferred_qualifications"):
                    description_parts.append("Preferred Qualifications: " + j["preferred_qualifications"])

                jobs_for_this_query.append({
                    "source_company": display_name,
                    "platform": "amazon",
                    "job_id": job_id,
                    "title": j.get("title", ""),
                    "location": j.get("normalized_location", ""),
                    "url": f"https://www.amazon.jobs{job_path}" if job_path else "",
                    "updated_at": posted_date,
                    "raw_description": " ".join(description_parts),
                })

            if not page_has_recent_job:
                break  # EARLY STOP: rest of this keyword's results are even older

            offset += page_size
            if offset >= data.get("hits", 0):
                break
            if offset > 5000:
                print(f"  [WARN] {display_name}: stopped after 5000 jobs (safety cap) for query '{base_query}'")
                break

        return jobs_for_this_query

    # Same pattern as fetch_pcsx: fetch once per keyword, then flatten
    # + de-dupe using the shared helper (common.py), so a job matching
    # two different keywords is only counted once.
    results_per_query = [fetch_for_one_query(base_query) for base_query in base_queries]
    return _merge_dedupe_by_job_id(results_per_query)
