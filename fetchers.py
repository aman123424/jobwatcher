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

import re
import requests
from datetime import datetime, timedelta, timezone

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


def _safe_get_text(url, **kwargs):
    """
    Same idea as _safe_get, but for endpoints that return HTML rather
    than JSON (e.g. a server-rendered page we need to scrape a value
    out of, like DE Shaw's Next.js buildId below). Returns the raw
    response text on success, or None on any failure.
    """
    try:
        resp = SESSION.get(url, timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"  [WARN] request failed for {url}: {e}")
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


# --- Early-stop-on-staleness, for platforms confirmed sorted newest-first ---
#
# WHY THIS EXISTS: state.py's seen-job diffing already guarantees no
# posting gets missed within a day, provided this runs every 15-30
# minutes as designed (see main.py) - a new posting is caught the very
# next run regardless of anything below. This is a SPEED optimization,
# not a correctness fix: several companies (Trimble, ABB, Target,
# Airbus, ServiceNow at real volume) were paging through hundreds or
# thousands of jobs — most of them old, already-seen postings — every
# single run. If a platform's results are confirmed sorted newest-first,
# we can stop paging once we're clearly past "recent" instead of
# fetching everything every time.
#
# 2 days, not 1: gives a buffer against exactly-24h boundary jitter
# between runs, and against Workday's day-level (not hour-level)
# "postedOn" labels — a job posted at 11pm and one posted at 1am the
# same calendar day can both say "Posted Yesterday" depending on when
# the label was generated, so treating "yesterday" as still worth
# fetching is the safe direction to round.
FRESHNESS_WINDOW_DAYS = 2

_WORKDAY_POSTED_ON_RE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)


def _workday_posted_on_days(posted_on: str):
    """
    Parse Workday's relative "postedOn" label into an integer day
    count — "Posted Today" -> 0, "Posted Yesterday" -> 1, "Posted 5
    Days Ago" -> 5, "Posted 30+ Days Ago" -> 30. Confirmed live against
    real labels from Visa and Barclays on 2026-08-26 (including the
    "30+" form, which needed the trailing "+" handled explicitly).

    Returns None for anything that doesn't match — callers should
    treat that as "can't tell, don't use it to stop early" rather than
    assuming it means "old" or "new".
    """
    if not posted_on:
        return None
    m = _WORKDAY_POSTED_ON_RE.search(posted_on)
    if not m:
        return None
    word = m.group(1).lower()
    if word == "today":
        return 0
    if word == "yesterday":
        return 1
    return int(m.group(2))


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

    3. EARLY-STOP ON STALENESS. Confirmed live on 2026-08-26: results
       come back sorted by releasedDate, newest first (unlike
       Greenhouse/Lever/Ashby, which are NOT sorted this way — verified
       and rejected before landing on this). A "?updatedAfter=..."
       query param LOOKED like the obvious fix but was tested live and
       is a silent no-op (totalFound didn't budge). So instead: once a
       full page's postings are all older than FRESHNESS_WINDOW_DAYS,
       stop — this is a real, evidence-backed shortcut, not a guess.
       See the FRESHNESS_WINDOW_DAYS comment above for why "why not
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
            if job_dt is None or job_dt >= cutoff:
                page_has_recent_job = True

            jobs.append({
                "source_company": display_name,
                "platform": "smartrecruiters",
                "job_id": job_id,
                "title": j.get("name", ""),
                "location": (j.get("location") or {}).get("city", ""),
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

    return jobs


def fetch_workday(display_name: str, tenant_wd_site: str) -> list[dict]:
    """
    Workday's job search endpoint (the "CXS" API their own career site
    frontend calls internally). This is Tier 2, not Tier 1 — meaning
    it's noticeably less clean than Greenhouse/Lever/Ashby/
    SmartRecruiters, in three specific ways explained inline below.

    STATUS: live-tested and working (this docstring previously said
    otherwise — that was written before Aman ran it for real; leaving
    this note rather than pretending it was always known-good, since
    the whole point of these docstrings is to reflect what's actually
    been verified, not what was hoped). Confirmed against KLA (49/49
    recovered) and APTIV (731/731 across 37 paginated requests) — see
    PROJECT_LOG.md for the full debugging trail that got it there,
    including the "total" field bug fixed below.

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

    EARLY STOP ON STALENESS (added 2026-08-26): confirmed live that
    Workday returns postings sorted newest-first — offset=0 was all
    "Posted Today", offset=100 had shifted to "Posted 5-6 Days Ago" on
    the same tenant. That's what makes stopping early here safe rather
    than a guess. This matters most for the biggest tenants (Trimble,
    ABB, Target, Airbus all hit the 2000-job safety cap on the first
    live run of this system) — without early-stop, a company with a
    genuinely huge total backlog gets its FETCH arbitrarily truncated
    at 2000 by that cap, which is worse than stopping deliberately once
    postings are confirmed stale (see FRESHNESS_WINDOW_DAYS above).
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

        page_has_recent_job = False
        for j in postings:
            external_path = j.get("externalPath", "")
            posted_on = j.get("postedOn")
            days_old = _workday_posted_on_days(posted_on)
            # days_old is None for an unrecognized label (Workday adds
            # new phrasing occasionally) - treat "can't tell" as recent
            # so we never stop early on a guess.
            if days_old is None or days_old < FRESHNESS_WINDOW_DAYS:
                page_has_recent_job = True

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
                "updated_at": posted_on,  # relative string, see docstring limitation 1
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

        # EARLY STOP: once a whole page has nothing recent left on it,
        # every later page is even older (confirmed sorted newest-first
        # — see docstring). No need to keep fetching postings state.py
        # already knows about from past runs.
        if not page_has_recent_job:
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

    NO RELIABLE DATE SORT FOUND: unlike fetch_workday/
    fetch_smartrecruiters below, `sort_by` was tested live with
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
    parts = host_domain_location.split("|")
    if len(parts) < 2:
        print(f"  [WARN] {display_name}: malformed pcsx identifier "
              f"'{host_domain_location}' (expected host|domain[|location[|queries]]) - skipping")
        return []
    host, domain = parts[0], parts[1]
    location = parts[2] if len(parts) > 2 else ""
    queries = [q.strip() for q in parts[3].split(",")] if len(parts) > 3 and parts[3] else [""]

    jobs_by_id = {}
    for query in queries:
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
                job_id = str(p.get("id", ""))
                position_url = p.get("positionUrl", "")
                locations = p.get("locations", [])
                # De-dupe across the multiple keyword searches above -
                # a job matching both "backend" and "software" would
                # otherwise get fetched (and later scored) twice.
                jobs_by_id[job_id] = {
                    "source_company": display_name,
                    "platform": "pcsx",
                    "job_id": job_id,
                    "title": p.get("name", ""),
                    "location": ", ".join(locations) if isinstance(locations, list) else (locations or ""),
                    "url": f"https://{host}{position_url}" if position_url else "",
                    "updated_at": _epoch_seconds_to_iso(p.get("postedTs")),
                    "raw_description": p.get("department", ""),
                }

            total_count = (data.get("data") or {}).get("count", 0)
            start += page_size
            if start >= total_count:
                break
            if start > 2000:
                print(f"  [WARN] {display_name}: stopped after 2000 jobs (safety cap) for query '{query}'")
                break

    return list(jobs_by_id.values())


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
        and same merge-by-job_id de-dupe as fetch_pcsx above (a single
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
    parts = country_base_query.split("|")
    country = parts[0] if len(parts) > 0 else ""
    base_queries = [q.strip() for q in parts[1].split(",")] if len(parts) > 1 and parts[1] else [""]

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=FRESHNESS_WINDOW_DAYS)).date()

    jobs_by_id = {}
    for base_query in base_queries:
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

            page_has_recent_job = False
            for j in job_list:
                job_id = str(j.get("id_icims", ""))
                job_path = j.get("job_path", "")
                posted_date = j.get("posted_date")  # human string e.g. "April 9, 2026", not ISO
                try:
                    job_date = datetime.strptime(posted_date, "%B %d, %Y").date() if posted_date else None
                except ValueError:
                    job_date = None  # unparseable - don't let it affect the stop decision either way
                if job_date is None or job_date >= cutoff_date:
                    page_has_recent_job = True

                # De-dupe across the multiple keyword searches above.
                jobs_by_id[job_id] = {
                    "source_company": display_name,
                    "platform": "amazon",
                    "job_id": job_id,
                    "title": j.get("title", ""),
                    "location": j.get("normalized_location", ""),
                    "url": f"https://www.amazon.jobs{job_path}" if job_path else "",
                    "updated_at": posted_date,
                    "raw_description": j.get("description_short") or j.get("description", ""),
                }

            if not page_has_recent_job:
                break  # EARLY STOP: rest of this keyword's results are even older

            offset += page_size
            if offset >= data.get("hits", 0):
                break
            if offset > 5000:
                print(f"  [WARN] {display_name}: stopped after 5000 jobs (safety cap) for query '{base_query}'")
                break

    return list(jobs_by_id.values())


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


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
    "pcsx": fetch_pcsx,
    "amazon": fetch_amazon,
    "deshaw": fetch_deshaw,
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
