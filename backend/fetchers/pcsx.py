"""fetchers/pcsx.py - the "pcsx" career-page search widget (Qualcomm, Microsoft)."""

from datetime import datetime, timedelta, timezone

from .common import FRESHNESS_WINDOW_DAYS, _merge_dedupe_by_job_id, _safe_get


def _epoch_seconds_to_iso(ts):
    """Convert Unix epoch-SECONDS to ISO. Qualcomm gives seconds, not
    milliseconds like Lever — mixing these up lands you in 1970."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def fetch_pcsx(display_name: str, host_domain_location: str) -> list[dict]:
    """
    "pcsx" is a career-page search widget shared by MULTIPLE companies —
    first found on Qualcomm's site (as "qualcomm_custom", back when it
    looked like a one-off), then confirmed byte-for-byte identical (same
    /api/pcsx/search path, same response shape: data.positions,
    data.count, id/name/locations/postedTs/department/positionUrl) on
    Microsoft's career site too, just under a different subdomain. This
    is a real vendor product, not something either company built
    themselves — worth checking any new "Custom Career Site" company
    against this pattern before assuming it needs a fully bespoke
    fetcher. Confirmed live for both via direct request on 2026-08-26.

    ARGUMENT FORMAT: pipe-separated "host|domain[|location[|queries]]", e.g.
        "careers.qualcomm.com|qualcomm.com|India"
        "apply.careers.microsoft.com|microsoft.com|India|software,backend,frontend,full stack"
      - host: the subdomain that actually serves /api/pcsx/search —
              varies per company, NOT always "careers.{domain}"
              (Microsoft's is "apply.careers.microsoft.com").
      - domain: the `domain=` query param the search API expects.
      - location: optional location filter. Qualcomm's original
        confirmed-working URL had "India" hardcoded; Microsoft's bare
        URL (no location) returned fine too — so it's genuinely
        optional, unlike domain/host.
      - queries: optional COMMA-separated list of keywords. Added after
        Microsoft's FIRST live run here pulled 2,000+ jobs and hit the
        safety cap — an unfiltered pcsx search returns EVERY open role
        at the company (Procurement Manager, retail roles, etc.), not
        just engineering ones. A single "software engineer" keyword
        fixed that (confirmed 113 for Microsoft), but a single keyword
        also risks missing real matches titled "Backend Developer" or
        "Full Stack Engineer" with no literal "software" in the title.
        So: run one search PER keyword and merge by job_id (a real
        posting matching more than one keyword — plausible, e.g.
        "Full Stack Software Engineer" — only gets counted once).
        Left Qualcomm on a single unfiltered pass since its existing
        India-only filter already keeps it to a reasonable ~540 without
        needing this at all — no reason to touch what already worked.

    NO RELIABLE DATE SORT FOUND: unlike fetchers/workday.py or
    fetchers/smartrecruiters.py, `sort_by` was tested live with
    several guessed values (postedDate, recent, date) against real
    postedTs timestamps and every one returned results in the exact
    same (non-chronological) order as the default "match" — so no
    early-stop-on-staleness here. Fine in practice: even the largest
    confirmed pcsx company (Qualcomm, ~540) pages fully in well under a
    minute, nowhere near Workday's multi-thousand-job scale that made
    early-stop worth building there.

    Page size (10) is assumed from the observed responses — no explicit
    page-size param appears in either company's URL.
    """
    # .split("|") turns "host|domain|location|queries" into a Python
    # LIST of 4 separate strings: ["host", "domain", "location", "queries"].
    # If the config string only has 2 parts (like Qualcomm's, which
    # skips location/queries), this list will only have 2 items - that's
    # why every access below past index 1 checks len(parts) first,
    # rather than assuming all 4 pieces are always present.
    parts = host_domain_location.split("|")
    if len(parts) < 2:
        print(f"  [WARN] {display_name}: malformed pcsx identifier "
              f"'{host_domain_location}' (expected host|domain[|location[|queries]]) - skipping")
        return []
    host, domain = parts[0], parts[1]
    # `parts[2] if len(parts) > 2 else ""` is Python's "conditional
    # expression" (a one-line if/else): use parts[2] when it actually
    # exists, otherwise fall back to an empty string. Same pattern is
    # used again below for `queries`.
    location = parts[2] if len(parts) > 2 else ""
    # `queries` ends up as a LIST of keywords to search one at a time,
    # e.g. "software,backend,frontend" -> ["software", "backend", "frontend"].
    # `[q.strip() for q in parts[3].split(",")]` is a "list comprehension"
    # - a compact way to write "build a new list by doing something to
    # every item in another list". Spelled out, it means: split the
    # 4th config piece on commas, then for each resulting piece (q),
    # strip off any leading/trailing spaces, and collect all of those
    # into a new list. If there's no 4th piece at all (Qualcomm's case),
    # we fall back to a list containing just one empty-string keyword —
    # which means "search with no keyword filter at all", i.e. get
    # everything, exactly like before this multi-keyword feature existed.
    queries = [q.strip() for q in parts[3].split(",")] if len(parts) > 3 and parts[3] else [""]

    def fetch_for_one_query(query):
        """
        Inner function (a function defined INSIDE another function).
        It's declared here, inside fetch_pcsx, specifically so it can
        directly use fetch_pcsx's own local variables (host, domain,
        location) without them having to be passed in as extra
        arguments every time - Python lets a nested function "see"
        everything in the function that contains it.

        This does ALL the actual page-by-page fetching for exactly ONE
        keyword search and returns that keyword's jobs as a list. It
        gets called once per keyword in `queries` below.
        """
        jobs_for_this_query = []
        start = 0
        page_size = 10

        while True:
            url = (
                f"https://{host}/api/pcsx/search"
                f"?domain={domain}&query={query}&location={location}&start={start}&sort_by=match&"
            )
            data = _safe_get(url)
            if not data or not isinstance(data, dict):
                break

            positions = (data.get("data") or {}).get("positions", [])
            if not positions:
                break

            for p in positions:
                position_url = p.get("positionUrl", "")
                locations = p.get("locations", [])
                jobs_for_this_query.append({
                    "source_company": display_name,
                    "platform": "pcsx",
                    "job_id": str(p.get("id", "")),
                    "title": p.get("name", ""),
                    "location": ", ".join(locations) if isinstance(locations, list) else (locations or ""),
                    "url": f"https://{host}{position_url}" if position_url else "",
                    "updated_at": _epoch_seconds_to_iso(p.get("postedTs")),
                    "raw_description": p.get("department", ""),
                })

            total_count = (data.get("data") or {}).get("count", 0)
            start += page_size
            if start >= total_count:
                break
            if start > 2000:
                print(f"  [WARN] {display_name}: stopped after 2000 jobs (safety cap) for query '{query}'")
                break

        return jobs_for_this_query

    # Run fetch_for_one_query once per keyword in `queries`, collecting
    # each keyword's results into a list-of-lists, e.g.
    #   [ [job, job], [job, job, job], [job] ]
    # then hand that to the shared helper (common.py) which flattens it
    # into one list AND removes duplicate jobs that matched more than
    # one keyword. This is the exact same merge step fetch_amazon uses
    # too - kept as one shared function instead of writing this de-
    # duping logic out twice.
    results_per_query = [fetch_for_one_query(query) for query in queries]
    jobs = _merge_dedupe_by_job_id(results_per_query)

    # FIX (2026-08-28): pcsx has NO reliable date sort (see this
    # function's docstring above - `sort_by` was tested live and does
    # nothing), so it never got the same early-stop-while-paginating
    # freshness trick fetch_workday/fetch_smartrecruiters use. That
    # meant EVERY relevant-titled job was getting the expensive,
    # deliberately-sequential per-job description enrichment below -
    # confirmed live on 2026-08-28: of 558 total India postings on
    # Qualcomm, only 14 were actually within the 2-day freshness
    # window; the other 544 ranged up to 409 DAYS old. Enriching all
    # ~550 sequentially (required to avoid the rate-limit errors
    # documented in _enrich_pcsx_descriptions' own docstring) is what
    # made a Qualcomm fetch take ~7 minutes on its own.
    #
    # Early-stop DURING pagination still isn't safe here (still no
    # reliable sort), but filtering the COMPLETE, already-fetched list
    # by each job's own postedTs (already parsed into updated_at above,
    # no extra request needed) doesn't need reliable ordering - it's
    # correct regardless of what order the postings came back in. This
    # is a plain post-fetch filter, not the page-by-page early-stop
    # fetch_workday/fetch_smartrecruiters use, but achieves the same
    # goal: don't pay for enriching (or scoring) a posting that's been
    # open for over a year.
    cutoff = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS)

    def is_recent(job):
        if not job["updated_at"]:
            return True  # can't tell - treat as recent rather than silently dropping it
        try:
            return datetime.fromisoformat(job["updated_at"]) >= cutoff
        except ValueError:
            return True  # unparseable - same reasoning as above

    stale_count = sum(1 for j in jobs if not is_recent(j))
    jobs = [j for j in jobs if is_recent(j)]
    if stale_count:
        print(f"  {display_name}: skipping {stale_count} posting(s) older than "
              f"{FRESHNESS_WINDOW_DAYS} days (not re-enriching/re-scoring every run)")

    # FIX (2026-08-27): the search results above only ever give
    # p.get("department") as raw_description - a one- or two-word
    # DEPARTMENT NAME like "Software Engineering", never the job's
    # actual description text. scoring scores a job by looking for
    # resume-skill keywords (C#, React, SQL, ...) in title+description,
    # so a real, strong-fit job with a department-only description
    # scores close to 0 and silently disappears from /jobs/best_match
    # - this is exactly what happened with a real Microsoft posting
    # Aman found manually and confirmed was missing from that endpoint,
    # even though it WAS being fetched correctly (verified live: it
    # was in these search results all along - it just had nothing real
    # to score against). Fixed by fetching each job's real description
    # from pcsx's separate "position_details" endpoint (confirmed live
    # to return a full HTML job description, not just a department
    # name) and overwriting raw_description with that before returning.
    _enrich_pcsx_descriptions(jobs, host, domain)
    return jobs


def _enrich_pcsx_descriptions(jobs: list[dict], host: str, domain: str) -> None:
    """
    Fetches the REAL job description for every job in `jobs` (a list
    of the normalized job dicts fetch_pcsx builds above) from pcsx's
    position_details endpoint, and overwrites each one's
    raw_description in place with it.

    "in place" is the important part here: this function doesn't
    return a new list - it directly modifies the dicts that are
    already sitting inside the `jobs` list fetch_pcsx passed in, the
    same way editing a spreadsheet cell doesn't require making a new
    spreadsheet. That's why fetch_pcsx above doesn't need to do
    anything with this function's return value (there isn't one, by
    design - see the `-> None` in the signature).

    DELIBERATELY SEQUENTIAL (ONE REQUEST AT A TIME), NOT CONCURRENT -
    this is the opposite choice from main.py's fetch_all_jobs(), and
    on purpose: that function's concurrency spreads its requests across
    MANY DIFFERENT companies' servers at once, which is exactly what
    concurrency is good for. This function instead sends every one of
    its requests to the SAME company's server, in a tight burst - a
    first version of this ran those concurrently too (first at 10 at
    once, then 4) and BOTH got real 429 "too many requests" errors back
    from Qualcomm's own site on live runs on 2026-08-27, because a
    burst of near-simultaneous requests to one server looks very
    different to that server than the same total number of requests
    spread across ten unrelated ones. Plain one-at-a-time is the fix -
    slower for a company with hundreds of relevant jobs, but it
    actually finishes with real descriptions instead of a pile of
    failed look-ups that undo this whole fix's purpose.

    A description look-up failing for one job (network hiccup, a job
    that got closed between the search call and this one, etc.) just
    leaves that one job's raw_description as whatever the search
    results already gave it (the department name) rather than failing
    the whole company's fetch - same "isolate failures" principle used
    everywhere else in this package.
    """
    for job in jobs:
        data = _safe_get(
            f"https://{host}/api/pcsx/position_details"
            f"?position_id={job['job_id']}&domain={domain}&hl=en"
        )
        description = (data.get("data") or {}).get("jobDescription") if isinstance(data, dict) else None
        if description:
            job["raw_description"] = description
