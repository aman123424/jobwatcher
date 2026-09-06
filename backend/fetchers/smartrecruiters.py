"""fetchers/smartrecruiters.py - SmartRecruiters' public Postings API."""

from datetime import datetime, timedelta, timezone

from scoring import is_relevant_title

from .common import FRESHNESS_WINDOW_DAYS, _safe_get


def fetch_smartrecruiters(display_name: str, company_id: str) -> list[dict]:
    """
    SmartRecruiters' public Postings API.

    URL shape:
        https://api.smartrecruiters.com/v1/companies/{company_id}/postings

    NOTE ON THE company_id ARGUMENT: SmartRecruiters identifiers are
    case-sensitive. ServiceNow's real careers page is at
    careers.smartrecruiters.com/servicenow (lowercase) — the value
    stored in companies.py must match exactly, or SmartRecruiters'
    API responds in an unexpected shape rather than a clean 404 (this
    is what caused the 'str' object has no attribute 'get' crash on
    the first live run — see the isinstance check below, which is
    the actual fix; correcting the slug just avoids triggering it for
    this specific company).

    Two differences from the others worth calling out because they're
    common real-world API patterns you'll hit again elsewhere:

    1. PAGINATION. SmartRecruiters only returns a limited number of
       postings per request (their default page size) and tells you
       how many more exist via a "totalFound" field. We loop, asking
       for the next page each time, until we've collected them all.
       Greenhouse/Lever/Ashby happen to return everything in one
       response for company-sized job boards, so we didn't need this
       there — but it's not safe to assume every API works that way.

    2. NO FULL DESCRIPTION IN THE LIST ENDPOINT - FIXED 2026-08-28.
       This "postings" list call only ever gave summary fields, not
       the full job description - getting that needs one extra API
       call PER JOB (a "detail" endpoint), confirmed live to exist at
       GET /v1/companies/{company_id}/postings/{posting_id} and to
       return real, substantial description text split into sections
       (jobAd.sections.jobDescription, .qualifications, etc). Doing
       that for EVERY posting would be a lot of extra requests for
       postings that were always going to get thrown away anyway (a
       Sales or HR posting matched under "software" precisely zero
       times) - so this only enriches postings whose TITLE already
       looks relevant (is_relevant_title(), imported from scoring -
       the exact same filter main.py applies to every other platform's
       results too, not a second copy of that list) AND that already
       survived the freshness early-stop below. See
       _enrich_smartrecruiters_descriptions() for the actual fetch.

    3. EARLY-STOP ON STALENESS. Confirmed live on 2026-08-26: results
       come back sorted by releasedDate, newest first (unlike
       Greenhouse/Lever/Ashby, which are NOT sorted this way — verified
       and rejected before landing on this). A "?updatedAfter=..."
       query param LOOKED like the obvious fix but was tested live and
       is a silent no-op (totalFound didn't budge). So instead: once a
       full page's postings are all older than FRESHNESS_WINDOW_DAYS,
       stop — this is a real, evidence-backed shortcut, not a guess.
       See common.py's FRESHNESS_WINDOW_DAYS comment for why "why not
       just miss nothing" isn't at risk here.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS)

    jobs = []
    offset = 0
    page_size = 100

    while True:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
            f"?limit={page_size}&offset={offset}"
        )
        data = _safe_get(url)
        if not data:
            break

        # DEFENSIVE CHECK — this is the actual fix for the crash seen
        # on the first live run ('str' object has no attribute 'get').
        # _safe_get() only guarantees "valid JSON", not "JSON shaped
        # the way we expect". A 200 response whose body happens to be
        # a bare JSON string (or a list, or anything that isn't a
        # dict) would otherwise reach data.get(...) below and crash
        # with an AttributeError whose message doesn't explain WHY.
        # This turns that into a clear, actionable log line instead,
        # and skips just this one company rather than crashing the
        # whole run.
        if not isinstance(data, dict):
            print(f"  [WARN] unexpected response shape from {url}: "
                  f"expected a JSON object, got {type(data).__name__} = {data!r}")
            break

        content = data.get("content", [])
        if not content:
            break

        page_has_recent_job = False
        for j in content:
            # "ref" is a STRING (SmartRecruiters' own API detail URL for
            # this posting), not a dict — calling .get("jobAd") on it is
            # what crashed. Build the real public URL ourselves instead:
            #   https://jobs.smartrecruiters.com/{company_identifier}/{id}
            company_identifier = (j.get("company") or {}).get("identifier", "")
            job_id = j.get("id", "")
            url = f"https://jobs.smartrecruiters.com/{company_identifier}/{job_id}" if company_identifier and job_id else ""

            released_date = j.get("releasedDate")
            job_dt = None
            if released_date:
                try:
                    job_dt = datetime.fromisoformat(released_date.replace("Z", "+00:00"))
                except ValueError:
                    pass  # unparseable date - don't let it affect the stop decision either way
            is_recent = job_dt is None or job_dt >= cutoff
            if is_recent:
                page_has_recent_job = True
            else:
                # BUG FIXED 2026-08-28: this used to append EVERY job on
                # the page regardless of is_recent, and only checked
                # page_has_recent_job AFTER the whole page was already
                # added - so the one page where freshness runs out mid-
                # page (or a page that's entirely stale but still gets
                # fetched because the PREVIOUS page had one recent job on
                # it) got included in full. Confirmed live: this let jobs
                # up to 258 hours (10.8 days) old through on a real
                # ServiceNow run, despite FRESHNESS_WINDOW_DAYS being 2.
                # Skipping stale jobs individually, right here, means a
                # page that's part-recent/part-stale only contributes its
                # genuinely recent jobs, not the whole page.
                continue

            # "fullLocation" (e.g. "Hyderabad, , India") rather than
            # just "city" (e.g. "Hyderabad" alone) - confirmed live
            # 2026-08-28 this is what the API actually gives, and using
            # only "city" was silently throwing the country away, which
            # is exactly what main.py's India-only location filter (see
            # scoring's is_india_location()) needs to see to work.
            location = (j.get("location") or {})
            jobs.append({
                "source_company": display_name,
                "platform": "smartrecruiters",
                "job_id": job_id,
                "title": j.get("name", ""),
                "location": location.get("fullLocation") or location.get("city", ""),
                "url": url,
                "updated_at": released_date,
                "raw_description": (j.get("function") or {}).get("label", ""),
            })

        # EARLY STOP: once a whole page is older than the freshness
        # window, every later page is even older (confirmed sorted
        # newest-first) - no point fetching them every run when
        # state.py already knows about all of them from past runs.
        if not page_has_recent_job:
            break

        offset += page_size
        if offset >= data.get("totalFound", 0):
            break  # we've now fetched every page

    _enrich_smartrecruiters_descriptions(jobs, company_id)
    return jobs


def _enrich_smartrecruiters_descriptions(jobs: list[dict], company_id: str) -> None:
    """
    Same idea as fetchers/pcsx.py's _enrich_pcsx_descriptions() (see
    that function's docstring for the full explanation of the "in
    place" mutation and why this runs SEQUENTIALLY, one request at a
    time, rather than concurrently - the exact same rate-limiting
    lesson learned live on Qualcomm applies here too), with one extra
    step first: only jobs whose TITLE already looks like a real
    Software Engineer role (is_relevant_title()) get a detail request
    at all. Everything else in `jobs` (Sales, HR, warehouse roles that
    happened to survive the freshness filter) is left exactly as it
    was - there's no point spending a request finding out a Sales
    posting's real description doesn't mention C#, when its TITLE
    already told us that.

    Combines THREE of the four sections SmartRecruiters gives per job
    into the new raw_description: jobDescription, qualifications (the
    section most likely to carry real "Required"/"Preferred" structure
    for scoring's JD-importance detection to find), and
    additionalInformation. companyDescription is the one deliberately
    left out (Aman's own call, 2026-08-28) - it's boilerplate about the
    COMPANY, not the job, and would only dilute keyword matching with
    irrelevant text.
    """
    for job in jobs:
        if not is_relevant_title(job["title"]):
            continue
        data = _safe_get(f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings/{job['job_id']}")
        if not data or not isinstance(data, dict):
            continue
        sections = ((data.get("jobAd") or {}).get("sections")) or {}
        parts = [
            (sections.get("jobDescription") or {}).get("text", ""),
            (sections.get("qualifications") or {}).get("text", ""),
            (sections.get("additionalInformation") or {}).get("text", ""),
        ]
        combined = " ".join(part for part in parts if part)
        if combined:
            job["raw_description"] = combined
