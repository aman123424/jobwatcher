"""fetchers/zoho_recruit.py - Zoho Recruit's public Career Site REST API (Tier 1-shaped, reusable across companies)."""

import requests

from scoring import is_relevant_title

from .common import SESSION, TIMEOUT, record_fetch_failure

LIST_PATH = "/recruit/v2/public/Job_Openings"


def fetch_zoho_recruit(display_name: str, domain: str) -> list[dict]:
    """
    Zoho Recruit's own public, unauthenticated Career Site REST API -
    a genuinely documented product endpoint (not reverse-engineered),
    confirmed identical across companies that have nothing else in
    common. Found chasing ITC's career site (recruitment.itcportal.com)
    - an earlier pass had wrongly concluded the only way to get that
    data was scraping a hidden-input JSON blob out of server-rendered
    HTML (see PROJECT_LOG.md), before this cleaner REST API was found
    live in a real browser network capture instead. That HTML-scraping
    approach is now dead code, deliberately not built - this replaces
    it entirely.

    STATUS: live-tested and working across THREE unrelated companies,
    proving this is a real, reusable platform pattern, not a one-off:
      - Wissen Technology (wissen.zohorecruit.in) - 43 postings, real
        India roles (Java/Fullstack/QA), Job_Description TRUNCATED in
        the list response (ends in "...") - needs the detail-fetch
        enrichment below.
      - ITC (recruitment.itcportal.com - a CUSTOM domain, not a bare
        zohorecruit.in subdomain) - 52 postings, real India roles,
        Job_Description already FULL in the list response - confirms
        truncation is a per-tenant setting, not universal, so
        enrichment below has to check per-job, not skip globally.
      - VinFast (vinfast.zohorecruit.com) - confirms the pattern holds
        on yet another company (Zoho Recruit's own customer
        testimonials page, zoho.com/recruit/customers, is what
        surfaced VinFast and ITC as real customers in the first place -
        Bosch and Deloitte's logos on that SAME page turned out to be
        misleading, see PROJECT_LOG.md: both companies' REAL
        India career sites run on entirely different platforms
        (SmartRecruiters and their own systems respectively) -
        a logo on a vendor's customer page is not itself confirmation,
        only a live test is). VinFast's own postings are Vietnam-based
        (Hanoi/Hai Phong), not India-relevant - included here only to
        prove the fetcher mechanism generalizes, not as a real
        candidate for CUSTOM_COMPANIES.

    ARGUMENT FORMAT: `domain` is just the bare hostname serving this
    company's Zoho Recruit career site - e.g. "wissen.zohorecruit.in"
    (a direct Zoho subdomain) or "recruitment.itcportal.com" (a
    company's own custom domain, mapped to the same underlying
    product) - confirmed BOTH shapes expose the exact same API path.
    No compound "|"-separated config needed, unlike Workday/Oracle
    Cloud/pcsx - this is as simple as a plain Greenhouse/Lever slug.

    NO PAGINATION ON THIS PUBLIC ENDPOINT, AND A CONFIRMED 200-JOB CAP -
    `page`/`per_page` (the param names the AUTHENTICATED Zoho Recruit
    API docs describe) get rejected outright here with a 400
    "EXTRA_PARAM_FOUND" error - this public, unauthenticated surface
    has a stricter allowlist than the full API, with no way to ask for
    a second page. VinFast (a large company, 200+ global postings)
    confirmed the actual ceiling: this endpoint returns exactly 200
    items, and - checked directly in a real browser -
    `window.jobs.length` on VinFast's OWN rendered career page is ALSO
    exactly 200. So this isn't a fetcher bug or a query mistake; it's
    the real product limit for this endpoint, matching Zoho's own
    documented default `per_page=200` for the authenticated API. A
    company with more than 200 TOTAL open roles worldwide would
    silently lose whatever's past that cutoff - not a concern for any
    company actually worth tracking here (India-relevant volume has
    stayed well under 200 on every company tested), but worth knowing
    before assuming this is safe for a very large global employer.
    """
    base_url = f"https://{domain}"
    list_url = f"{base_url}{LIST_PATH}"

    try:
        resp = SESSION.get(
            list_url,
            params={"pagename": "Careers", "source": "CareerSite"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"  [WARN] request failed for {list_url}: {e}")
        record_fetch_failure(str(e))
        return []
    except ValueError as e:
        print(f"  [WARN] bad JSON from {list_url}: {e}")
        record_fetch_failure(str(e))
        return []

    if not isinstance(data, dict) or data.get("code") != "success":
        print(f"  [WARN] Zoho Recruit API error from {list_url}: {data}")
        record_fetch_failure(f"Zoho Recruit API error from {list_url}")
        return []

    jobs = []
    for p in data.get("data") or []:
        job_id = str(p.get("id", ""))
        # City/State/Country - same "join whatever parts exist" pattern
        # fetch_oracle_cloud already uses, since State isn't present on
        # every tenant (confirmed present for ITC, absent on some
        # Skyroot postings during the earlier research pass).
        location = ", ".join(part for part in (p.get("City"), p.get("State"), p.get("Country")) if part)
        jobs.append({
            "source_company": display_name,
            "platform": "zoho_recruit",
            "job_id": job_id,
            "title": p.get("Posting_Title", ""),
            "location": location,
            # "$url" is the real, public, company-branded apply link
            # (e.g. careers.wissen.com/jobs/..., not the bare Zoho
            # domain) - confirmed present on every posting tested so
            # far; falls back to a constructed URL on the off chance
            # it's ever missing, rather than shipping a blank link.
            "url": p.get("$url") or f"{base_url}/jobs/Careers/{job_id}",
            # "MM/DD/YYYY" - confirmed identical on both ITC and Wissen
            # despite everything else about their setups differing -
            # see job_dates.py's own "zoho_recruit" branch.
            "updated_at": p.get("Date_Opened"),
            "raw_description": p.get("Job_Description") or p.get("Posting_Title", ""),
        })

    _enrich_zoho_recruit_descriptions(jobs, base_url)
    return jobs


def _enrich_zoho_recruit_descriptions(jobs: list[dict], base_url: str) -> None:
    """
    Same in-place mutation, same sequential-not-concurrent, same
    is_relevant_title() pre-filter every other enrichment step in this
    package uses - but with an EXTRA check first, unique to this
    platform: only re-fetch when the description we already have looks
    genuinely truncated (ends in "...", the exact signal confirmed live
    on Wissen's postings). Re-fetching every relevant job regardless,
    the way fetch_workday/fetch_oracle_cloud always do, would be
    needless extra requests for a tenant like ITC that already gives
    the full text in the list response - this platform is the first
    one confirmed to vary per-tenant on that specific point.

    The per-job detail endpoint is the SAME list path, with the job's
    numeric id appended - e.g. .../public/Job_Openings/80238...99 -
    confirmed live it returns the identical response shape (a `data`
    list with one item) as the list endpoint, just scoped to one job,
    with the real, untruncated Job_Description.
    """
    for job in jobs:
        if not is_relevant_title(job["title"]):
            continue
        if not job["raw_description"].rstrip().endswith("..."):
            continue

        detail_url = f"{base_url}{LIST_PATH}/{job['job_id']}"
        try:
            resp = SESSION.get(
                detail_url,
                params={"pagename": "Careers", "source": "CareerSite"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {detail_url}: {e}")
            record_fetch_failure(str(e))
            continue
        except ValueError as e:
            print(f"  [WARN] bad JSON from {detail_url}: {e}")
            record_fetch_failure(str(e))
            continue

        if not isinstance(data, dict) or data.get("code") != "success":
            continue
        items = data.get("data") or []
        if not items:
            continue
        description = items[0].get("Job_Description")
        if description:
            job["raw_description"] = description
