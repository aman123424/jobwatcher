"""
fetchers.py
===========

This is the part of the system that actually talks to each ATS
platform's API over the network and gets a list of open jobs back.

THE CORE IDEA — NORMALIZATION:
Greenhouse, Lever, Ashby, and SmartRecruiters are four different
companies with four different APIs. Each one names its fields
differently (Greenhouse calls a job's link "absolute_url", Lever calls
it "hostedUrl", etc). If we let those differences leak into the rest
of our program, every other file (scoring.py, state.py, main.py) would
need to know about all four shapes — messy, and painful to extend.

So every fetch_* function below has the SAME job: call the API, then
translate whatever it returns into one common shape (a plain Python
dict) that looks identical no matter which platform it came from:

    {
        "source_company": "Razorpay",     # from companies.py, not the API
        "platform": "greenhouse",
        "job_id": "12345",                # unique within that platform
        "title": "Software Engineer II",
        "location": "Bengaluru, India",
        "url": "https://job-boards.greenhouse.io/.../jobs/12345",
        "updated_at": "2026-08-20T09:15:00",   # ISO 8601 string, or None
        "raw_description": "...",         # plain text, used for scoring
    }

This pattern — "adapter functions that normalize different sources
into one shape" — is genuinely useful backend design, not just
specific to this project. You'll see the same idea called an "adapter"
or "translator" layer in a lot of real systems that talk to multiple
external APIs.

WHY EACH FUNCTION CATCHES ITS OWN ERRORS:
If Razorpay's API is briefly down, we still want the other 21
companies to be checked. So each fetch_* function catches its own
exceptions and returns an empty list on failure, rather than letting
one bad company crash the whole run. main.py additionally logs WHICH
company failed, so failures are visible, not silently swallowed.
"""

import requests
from datetime import datetime, timezone

# A single shared "session" object, reused across all requests.
# WHY: each request through a session can reuse the same underlying
# TCP connection (via HTTP keep-alive) instead of opening a fresh one
# every time — faster, and more polite to the servers we're calling.
# We also set a real User-Agent header; some APIs quietly reject
# requests that look like they're not coming from a real client.
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "jobwatch/0.1 (personal job search tool; contact: amankulwal27@gmail.com)"
})

# Every network call gets a timeout. WHY THIS MATTERS: without a
# timeout, if a server hangs and never responds, our program would
# freeze on that one request forever instead of moving on to the next
# company. (seconds to connect, seconds to wait for a response)
TIMEOUT = (5, 15)


def _safe_get(url, **kwargs):
    """
    Shared helper: does a GET request, and turns network-level and
    HTTP-level failures into a single, predictable outcome (None)
    instead of letting exceptions escape and crash the caller.

    Returns the parsed JSON body on success, or None on any failure
    (network error, timeout, non-200 status, or invalid JSON).
    """
    try:
        resp = SESSION.get(url, timeout=TIMEOUT, **kwargs)
        # raise_for_status() turns HTTP error codes (404, 500, etc.)
        # into a Python exception, so we can handle them in the same
        # except block as network errors below, instead of writing a
        # separate "if resp.status_code != 200" check every time.
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        # This catches: connection errors, timeouts, DNS failures,
        # and (because of raise_for_status above) HTTP error codes.
        print(f"  [WARN] request failed for {url}: {e}")
        return None
    except ValueError as e:
        # json() raises ValueError if the response body isn't valid
        # JSON at all (e.g. the API returned an HTML error page).
        print(f"  [WARN] bad JSON from {url}: {e}")
        return None


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
            "url": j.get("absolute_url", ""),
            "updated_at": j.get("updated_at"),  # already ISO 8601
            "raw_description": j.get("content", ""),  # HTML, stripped later
        })
    return jobs


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
            # the time this data leaves fetchers.py, EVERY platform's
            # "updated_at" looks the same (an ISO 8601 string).
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

    2. NO FULL DESCRIPTION IN THE LIST ENDPOINT. This "postings" list
       call only gives summary fields, not the full job description.
       Getting the full text would mean one extra API call PER JOB
       (a "detail" endpoint), which is a lot of extra requests for
       marginal benefit here — so for now we score SmartRecruiters
       jobs on title + department/function only, and note that as a
       known limitation (see scoring.py).
    """
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

        for j in content:
            # "ref" is a STRING (SmartRecruiters' own API detail URL for
            # this posting), not a dict — calling .get("jobAd") on it is
            # what crashed. Build the real public URL ourselves instead:
            #   https://jobs.smartrecruiters.com/{company_identifier}/{id}
            company_identifier = (j.get("company") or {}).get("identifier", "")
            job_id = j.get("id", "")
            url = f"https://jobs.smartrecruiters.com/{company_identifier}/{job_id}" if company_identifier and job_id else ""

            jobs.append({
                "source_company": display_name,
                "platform": "smartrecruiters",
                "job_id": job_id,
                "title": j.get("name", ""),
                "location": (j.get("location") or {}).get("city", ""),
                "url": url,
                "updated_at": j.get("releasedDate"),
                "raw_description": (j.get("function") or {}).get("label", ""),
            })

        offset += page_size
        if offset >= data.get("totalFound", 0):
            break  # we've now fetched every page

    return jobs


def fetch_workday(display_name: str, tenant_wd_site: str) -> list[dict]:
    """
    Workday's job search endpoint (the "CXS" API their own career site
    frontend calls internally). This is Tier 2, not Tier 1 — meaning
    it's noticeably less clean than Greenhouse/Lever/Ashby/
    SmartRecruiters, in three specific ways explained inline below.

    IMPORTANT — UNLIKE EVERY OTHER FETCH_* FUNCTION IN THIS FILE, THIS
    ONE HAS NOT BEEN VALIDATED AGAINST A LIVE RESPONSE. Workday's
    domain isn't reachable from my sandbox any more than Greenhouse's
    was, and unlike Greenhouse/Lever/Ashby I didn't have independent
    third-party documentation confirming the exact field names for
    Workday specifically. This function is written against the
    well-known, widely-reverse-engineered shape of this endpoint (the
    same pattern countless public Workday scrapers use) — but "widely
    known" is not the same as "verified for OUR specific tenants."
    Treat your first `python3 fetchers.py` run against a Workday
    company with real suspicion, more than you did for Tier 1.

    ARGUMENT FORMAT: tenant_wd_site is the pipe-separated 3-part
    identifier from companies.py, e.g. "visa|wd5|visa" meaning:
      - tenant = "visa"   (Workday customer ID)
      - wd_num = "wd5"    (which Workday data-center cluster they're on)
      - site   = "visa"   (the specific career site name on that tenant —
                            some companies run multiple career sites,
                            e.g. one for corporate roles, one for retail)
    We split this apart below to build the URL.

    URL AND METHOD: unlike the three other platforms, this is a POST
    request with a JSON body, not a GET with query parameters. Workday
    uses this shape because the frontend needs to send search filters
    (location, category, keywords) as structured JSON, not a simple
    URL — we send an "empty search" (no filters, no keyword) to get
    every open posting.

    KNOWN LIMITATIONS (read before trusting this data the way you
    trust Tier 1):
      1. POSTED DATE IS IMPRECISE. Workday's list response typically
         gives a human string like "Posted Today" or "Posted 3 Days
         Ago", not an exact timestamp like Greenhouse/Lever/Ashby give
         us. We store it as-is in updated_at — it's still useful to a
         human reading matches_log.csv, just not precise to the
         minute the way Tier 1 is.
      2. NO FULL DESCRIPTION IN THIS RESPONSE. Same tradeoff as
         SmartRecruiters (see that function's docstring) — getting
         the full text needs one extra request PER JOB, which we're
         not doing here. Workday jobs get scored on title text only.
      3. SOME WORKDAY TENANTS HAVE BOT PROTECTION. A 403 here doesn't
         necessarily mean the identifier is wrong — some companies
         put Cloudflare or similar in front of their Workday site.
         If EVERY Workday company 403s but Tier 1 companies work
         fine, that's the likely explanation, and there's no simple
         fix for it (it would need a headless browser, not a plain
         HTTP request — a much bigger piece of work, not attempted here).
    """
    parts = tenant_wd_site.split("|")
    if len(parts) != 3:
        print(f"  [WARN] {display_name}: malformed Workday identifier "
              f"'{tenant_wd_site}' (expected tenant|wdN|site) - skipping")
        return []
    tenant, wd_num, site = parts

    url = f"https://{tenant}.{wd_num}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"

    jobs = []
    offset = 0
    page_size = 20  # Workday's own frontend typically requests 20 at a time

    while True:
        # No delay between pages. Tested with a 1.5s gap and without —
        # identical results either way (KLA's total field lied at
        # offset=20 both times). That ruled out rate limiting as the
        # cause; the real bug was trusting the "total" field at all
        # (fixed below, in the stopping condition). Removed the delay
        # since it wasn't doing anything — but if a full run against a
        # high-volume company (IQVIA, 90+ pages) ever shows actual
        # request failures or 403s, that's a genuinely different
        # symptom from what we've seen so far, and would be worth
        # revisiting this.
        body = {"appliedFacets": {}, "limit": page_size, "offset": offset, "searchText": ""}
        try:
            resp = SESSION.post(url, json=body, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {url}: {e}")
            break
        except ValueError as e:
            print(f"  [WARN] bad JSON from {url}: {e}")
            break

        if not isinstance(data, dict):
            print(f"  [WARN] unexpected response shape from {url}: "
                  f"expected a JSON object, got {type(data).__name__}")
            break

        postings = data.get("jobPostings", [])
        # Workday's "total" field is NOT extracted or used here anymore.
        # Confirmed unreliable past page 1 on every tenant tested (KLA:
        # 3 pages, APTIV: 37 pages, zero exceptions) — it silently drops
        # to 0 while the page itself keeps returning real postings. The
        # stopping condition below relies only on the page's actual
        # content, never on this field. See git history / conversation
        # log if you need the full debugging trail that found this.

        for j in postings:
            external_path = j.get("externalPath", "")
            jobs.append({
                "source_company": display_name,
                "platform": "workday",
                # Workday's list response doesn't give a separate clean
                # numeric ID field the way Greenhouse/Lever/Ashby do —
                # externalPath (e.g. "/job/Bengaluru/Software-Engineer_R12345")
                # is unique per posting and stable, so we use it as our
                # job_id directly rather than trying to extract just the
                # requisition number out of it.
                "job_id": external_path,
                "title": j.get("title", ""),
                "location": j.get("locationsText", ""),
                "url": f"https://{tenant}.{wd_num}.myworkdayjobs.com/{site}{external_path}",
                "updated_at": j.get("postedOn"),  # relative string, see docstring limitation 1
                "raw_description": j.get("title", ""),  # see docstring limitation 2 - title only
            })

        # STOPPING CONDITION — based on the page itself, not "total".
        # A page with fewer postings than we asked for (page_size) is
        # a genuine last page, whether that's a partial page (e.g. 9
        # of 20) or a fully empty one. This is what actually broke
        # before: trusting "total" meant a real page of jobs got
        # discarded as "we're done" the instant total lied. A short
        # page is a fact we observed directly — nothing to trust.
        if len(postings) < page_size:
            break

        offset += page_size
        if offset > 2000:  # safety cap - a company should never realistically have this many
            print(f"  [WARN] {display_name}: stopped after 2000 jobs (safety cap)")
            break

    return jobs


# This dict is how main.py picks the right function for each company,
# without a long if/elif/elif chain. "platform string from companies.py"
# -> "the function that knows how to fetch that platform".
def _epoch_seconds_to_iso(ts):
    """Convert Unix epoch-SECONDS to ISO. Qualcomm gives seconds, not
    milliseconds like Lever — mixing these up lands you in 1970."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def fetch_qualcomm(display_name: str, base_domain: str) -> list[dict]:
    """
    Qualcomm-specific — their real career site runs a separate search
    layer at careers.qualcomm.com/api/pcsx/search, not the generic
    Workday wday/cxs pattern (which 422'd both runs). Built from
    Aman's confirmed real response, not guessed. One-off, not a
    reusable pattern (no evidence yet other companies share it).

    &location=India is hardcoded — part of the confirmed working URL,
    kept deliberately so Qualcomm's own search filters for us.

    Page size (10) is assumed from the one observed response — no
    explicit page-size param was in the confirmed URL.
    """
    jobs = []
    start = 0
    page_size = 10

    while True:
        url = (
            f"https://careers.{base_domain}/api/pcsx/search"
            f"?domain={base_domain}&query=&location=India&start={start}&sort_by=match&"
        )
        data = _safe_get(url)
        if not data or not isinstance(data, dict):
            break

        positions = (data.get("data") or {}).get("positions", [])
        if not positions:
            break

        for p in positions:
            position_url = p.get("positionUrl", "")
            jobs.append({
                "source_company": display_name,
                "platform": "qualcomm_custom",
                "job_id": str(p.get("id", "")),
                "title": p.get("name", ""),
                "location": ", ".join(p.get("locations", [])),
                "url": f"https://careers.{base_domain}{position_url}" if position_url else "",
                "updated_at": _epoch_seconds_to_iso(p.get("postedTs")),
                "raw_description": p.get("department", ""),
            })

        total_count = (data.get("data") or {}).get("count", 0)
        start += page_size
        if start >= total_count:
            break
        if start > 2000:
            print(f"  [WARN] {display_name}: stopped after 2000 jobs (safety cap)")
            break

    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
    "qualcomm_custom": fetch_qualcomm,
}


if __name__ == "__main__":
    # Quick manual test: run `python3 fetchers.py` to sanity-check ONE
    # known-good company end to end, without running the whole system.
    # This is the live test I couldn't do from my sandbox earlier —
    # this is that test, for you to run.
    test_jobs = fetch_greenhouse("Razorpay", "razorpaysoftwareprivatelimited")
    print(f"Fetched {len(test_jobs)} jobs from Razorpay's Greenhouse board.")
    if test_jobs:
        print("Sample job:")
        sample = test_jobs[0]
        for k, v in sample.items():
            preview = (v[:80] + "...") if isinstance(v, str) and len(v) > 80 else v
            print(f"  {k}: {preview}")
