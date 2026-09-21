"""fetchers/workday.py - Workday's job search endpoint (Tier 2)."""

import requests

from job_dates import workday_posted_on_days
from scoring import is_relevant_title

from .common import FRESHNESS_WINDOW_DAYS, SESSION, TIMEOUT, _safe_get, record_fetch_failure


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
      2. NO FULL DESCRIPTION IN THIS RESPONSE - FIXED 2026-08-28. Same
         tradeoff SmartRecruiters had (see that function's docstring)
         and the same fix: a real per-job detail endpoint exists
         (confirmed live at GET {this same tenant/wdN/site base}
         /job{externalPath} - literally the list endpoint's own URL
         with "/jobs" swapped for "/job{externalPath}"), returning
         jobPostingInfo.jobDescription with real, substantial text
         (7,878 chars confirmed on a real Visa posting). Same
         "only enrich jobs whose title already looks relevant" filter
         as SmartRecruiters too - see _enrich_workday_descriptions().
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
    postings are confirmed stale (see FRESHNESS_WINDOW_DAYS in common.py).
    """
    parts = tenant_wd_site.split("|")
    if len(parts) not in (3, 4):
        print(f"  [WARN] {display_name}: malformed Workday identifier "
              f"'{tenant_wd_site}' (expected tenant|wdN|site[|searchText]) - skipping")
        record_fetch_failure(f"malformed Workday identifier '{tenant_wd_site}'")
        return []
    tenant, wd_num, site = parts[:3]
    # OPTIONAL 4th part: Workday's own server-side searchText. Added
    # 2026-09-21 for Target, whose tenant started listing ~2000 mostly-US
    # store postings ALL as "Posted Today", so the early-stop never
    # fired and 100 sequential pages took ~153s (over the 120s Lambda
    # limit, breaking every refresh). "Bangalore" scopes it to 75
    # postings (4 requests) and was confirmed to be a superset of
    # "Bengaluru". Not "India" - that matches Indiana's "IN" state code.
    search_text = parts[3] if len(parts) == 4 else ""

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
        body = {"appliedFacets": {}, "limit": page_size, "offset": offset, "searchText": search_text}
        try:
            resp = SESSION.post(url, json=body, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {url}: {e}")
            record_fetch_failure(str(e))
            break
        except ValueError as e:
            print(f"  [WARN] bad JSON from {url}: {e}")
            record_fetch_failure(str(e))
            break

        if not isinstance(data, dict):
            print(f"  [WARN] unexpected response shape from {url}: "
                  f"expected a JSON object, got {type(data).__name__}")
            record_fetch_failure(f"unexpected response shape from {url}")
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
            days_old = workday_posted_on_days(posted_on)
            # days_old is None for an unrecognized label (Workday adds
            # new phrasing occasionally) - treat "can't tell" as recent
            # so we never stop early on a guess.
            is_recent = days_old is None or days_old < FRESHNESS_WINDOW_DAYS
            if is_recent:
                page_has_recent_job = True
            else:
                # BUG FIXED 2026-08-28: same fix as fetch_smartrecruiters
                # - this used to append every posting on the page
                # regardless of is_recent, only checking page_has_recent_job
                # AFTER the whole page was already added. That let an
                # entire page of stale postings through whenever an
                # earlier page still had at least one recent one on it.
                # Skipping stale postings individually, right here, means
                # a part-recent/part-stale page only contributes its
                # genuinely recent postings.
                continue

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

    _enrich_workday_descriptions(jobs, tenant, wd_num, site)
    return jobs


def _enrich_workday_descriptions(jobs: list[dict], tenant: str, wd_num: str, site: str) -> None:
    """
    Same idea, same "in place" mutation, and same SEQUENTIAL-not-
    concurrent reasoning as fetchers/pcsx.py's _enrich_pcsx_descriptions
    and fetchers/smartrecruiters.py's _enrich_smartrecruiters_descriptions
    - only enrich jobs whose title already looks like a real Software
    Engineer role (is_relevant_title()), one request at a time.

    Workday's detail endpoint is the exact same cxs base URL the list
    endpoint uses, just with the job's own externalPath appended
    instead of "/jobs" - e.g. list is .../wday/cxs/visa/visa/jobs,
    detail for one posting is .../wday/cxs/visa/visa/job/US---New-
    York-NY/Some-Job-Title_REF12345. Confirmed live: a plain GET (not
    the list endpoint's POST), returning jobPostingInfo.jobDescription
    as real HTML text.

    NOTE ON external_path: it already comes back from Workday starting
    with "/job/..." (see fetch_workday above), so it's appended
    directly here with NO extra "/job" in between - a first version of
    this added one anyway, building a broken ".../job/job/..." URL that
    404's/422's on every single request. Confirmed live this fixed it.
    """
    for job in jobs:
        if not is_relevant_title(job["title"]):
            continue
        external_path = job["job_id"]  # see fetch_workday above - externalPath IS the job_id here, and already starts with "/job/..."
        data = _safe_get(f"https://{tenant}.{wd_num}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{external_path}")
        if not data or not isinstance(data, dict):
            continue
        description = (data.get("jobPostingInfo") or {}).get("jobDescription", "")
        if description:
            job["raw_description"] = description
