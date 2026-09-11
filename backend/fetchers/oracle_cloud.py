"""fetchers/oracle_cloud.py - Oracle Fusion Cloud Recruiting's job search endpoint (Tier 2, alongside Workday)."""

import requests

from job_dates import oracle_cloud_posted_date_days
from scoring import is_relevant_title

from .common import FRESHNESS_WINDOW_DAYS, SESSION, TIMEOUT, record_fetch_failure

# 25 - Oracle's own Candidate Experience frontend requests this many at
# a time in the real browser network capture this fetcher is built
# from (see PROJECT_LOG.md for the Honeywell/Texas Instruments
# live-verification pass this came out of).
PAGE_SIZE = 25


def fetch_oracle_cloud(display_name: str, tenant_dc_site: str) -> list[dict]:
    """
    Oracle Fusion Cloud Recruiting's public REST API
    (`recruitingCEJobRequisitions`) - officially documented at
    docs.oracle.com, not a reverse-engineered internal endpoint the
    way Workday's CXS API is. Genuinely Tier 1-shaped underneath (a
    plain unauthenticated GET returning real JSON, real ISO dates, a
    real per-job detail call for full descriptions) - filed alongside
    Workday in Tier 2 anyway because, same as Workday, the per-company
    IDENTIFIER is an opaque, unguessable tenant code that has to be
    found by live-inspecting a real company's careers page, not
    derived from the company name the way a Greenhouse/Lever slug is.

    STATUS: live-tested and working. Confirmed against Honeywell
    (ibqbjb|ocs|CX_1 - 1,334 total open requisitions, real India
    locations) and Texas Instruments (edbz|us2|CX_1 - 188 matching
    "software", real India roles in Bengaluru) - see PROJECT_LOG.md.
    An earlier research pass had wrongly ruled Oracle Cloud out
    entirely after only checking whether the public career page had a
    server-rendered HTML fallback (it doesn't) - the real API was
    found by watching Texas Instruments' own page make this exact
    call in a live browser network capture, not by reading page source.

    ARGUMENT FORMAT: tenant_dc_site is the pipe-separated 3-part
    identifier from companies.py, e.g. "edbz|us2|CX_1" meaning:
      - tenant = "edbz"  (Oracle customer/tenant code - opaque, found by
                          inspecting a company's real careers page, same
                          as Workday's tenant)
      - dc     = "us2"   (which Oracle data-center cluster they're on -
                          e.g. "us2", "ocs" - also company-specific)
      - site   = "CX_1"  (the candidate-experience "site number" - CX_1
                          is the default/most common value seen so far,
                          but a company running multiple career sites
                          could have others, same reasoning as Workday's
                          per-company "site" segment)
    We split this apart below to build both the search URL and the
    per-job detail URL.

    URL AND METHOD: a GET request with the search criteria packed into
    one `finder` query parameter (Oracle's own REST convention, not
    something built ad hoc here) - `findReqs;siteNumber={site},
    limit={n},offset={n},sortBy=POSTING_DATES_DESC`. Deliberately no
    `keyword=` filter - same reasoning fetch_workday() gives for its
    "empty search": we want every open posting, not a pre-filtered
    subset, since is_relevant_title() (ingest.py) already does that
    filtering centrally for every platform.

    EARLY STOP ON STALENESS: confirmed live that `sortBy=
    POSTING_DATES_DESC` genuinely sorts newest-first (offset=0 was all
    "PostedDate": today; offset=100 on the same tenant had shifted to
    2-3 days earlier) - same "confirmed, not assumed" bar
    FRESHNESS_WINDOW_DAYS's own module docstring asks for. This matters
    here specifically because Honeywell alone has 1,334 total open
    requisitions - fetching all of them every refresh would be exactly
    the wasted-work problem Workday's early-stop already solves for
    its own large tenants.

    ONE CONFIRMED METADATA GOTCHA: the response's own `hasMore` field
    is NOT trusted as a stopping signal - confirmed live it reads
    `false` even on a page that's provably not the last one (a
    same-tenant later page returned a full page of DIFFERENT jobs
    right after). Same class of bug as Workday's unreliable `total`
    field (see fetch_workday's own docstring) - the stopping condition
    below is based only on the page's own actual returned length,
    never on a metadata field claiming to summarize it.
    """
    parts = tenant_dc_site.split("|")
    if len(parts) != 3:
        print(f"  [WARN] {display_name}: malformed Oracle Cloud identifier "
              f"'{tenant_dc_site}' (expected tenant|dc|site) - skipping")
        record_fetch_failure(f"malformed Oracle Cloud identifier '{tenant_dc_site}'")
        return []
    tenant, dc, site = parts

    base_url = f"https://{tenant}.fa.{dc}.oraclecloud.com"
    list_url = f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    jobs = []
    offset = 0

    while True:
        finder = f"findReqs;siteNumber={site},limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
        try:
            resp = SESSION.get(
                list_url,
                params={
                    "onlyData": "true",
                    "expand": "requisitionList.workLocation",
                    "finder": finder,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {list_url} (offset={offset}): {e}")
            record_fetch_failure(str(e))
            break
        except ValueError as e:
            print(f"  [WARN] bad JSON from {list_url} (offset={offset}): {e}")
            record_fetch_failure(str(e))
            break

        if not isinstance(data, dict):
            print(f"  [WARN] unexpected response shape from {list_url}: "
                  f"expected a JSON object, got {type(data).__name__}")
            record_fetch_failure(f"unexpected response shape from {list_url}")
            break

        items = data.get("items") or []
        if not items:
            break
        postings = items[0].get("requisitionList", [])

        page_has_recent_job = False
        for j in postings:
            posted_date = j.get("PostedDate")
            days_old = oracle_cloud_posted_date_days(posted_date)
            # days_old is None for an unparseable/missing date - treat
            # "can't tell" as recent, same reasoning fetch_workday()
            # applies to an unrecognized postedOn label: never stop
            # early on a guess.
            is_recent = days_old is None or days_old < FRESHNESS_WINDOW_DAYS
            if is_recent:
                page_has_recent_job = True
            else:
                continue

            req_id = str(j.get("Id", ""))
            location = j.get("PrimaryLocation", "") or ""
            jobs.append({
                "source_company": display_name,
                "platform": "oracle_cloud",
                "job_id": req_id,
                "title": j.get("Title", ""),
                "location": location,
                "url": f"{base_url}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}",
                "updated_at": posted_date,  # a real "YYYY-MM-DD" date, see job_dates.py's oracle_cloud_posted_date_days
                # No full description in the list response (see
                # _enrich_oracle_cloud_descriptions below) - ShortDescriptionStr
                # is a real short summary field Oracle does return here,
                # a better placeholder than title alone until enriched.
                "raw_description": j.get("ShortDescriptionStr") or j.get("Title", ""),
            })

        # STOPPING CONDITION - based on the page's own actual length,
        # not any metadata field (see docstring's "hasMore gotcha").
        if len(postings) < PAGE_SIZE:
            break

        if not page_has_recent_job:
            break

        offset += PAGE_SIZE
        if offset > 2000:  # safety cap - same as fetch_workday, a company should never realistically need more
            print(f"  [WARN] {display_name}: stopped after 2000 jobs (safety cap)")
            break

    _enrich_oracle_cloud_descriptions(jobs, base_url, site)
    return jobs


def _enrich_oracle_cloud_descriptions(jobs: list[dict], base_url: str, site: str) -> None:
    """
    Same idea, same in-place mutation, and same sequential-not-
    concurrent reasoning as fetch_workday's own
    _enrich_workday_descriptions - only enrich jobs whose title already
    looks like a real Software Engineer role (is_relevant_title), one
    request at a time, rather than fetching full descriptions for
    every posting up front.

    recruitingCEJobRequisitionDetails is a SEPARATE endpoint from the
    list one - confirmed live it returns ExternalDescriptionStr as
    real HTML job-description text (1,023 chars confirmed on a real
    Honeywell AI Engineer posting - see PROJECT_LOG.md). The finder
    parameter name is genuinely "Id" (capital I), not "requisitionId" -
    confirmed live after "requisitionId" 400'd with "not valid".
    """
    for job in jobs:
        if not is_relevant_title(job["title"]):
            continue
        detail_url = f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        try:
            resp = SESSION.get(
                detail_url,
                params={"onlyData": "true", "finder": f'ById;Id="{job["job_id"]}",siteNumber={site}'},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] request failed for {detail_url} (job {job['job_id']}): {e}")
            record_fetch_failure(str(e))
            continue
        except ValueError as e:
            print(f"  [WARN] bad JSON from {detail_url} (job {job['job_id']}): {e}")
            record_fetch_failure(str(e))
            continue

        if not isinstance(data, dict):
            continue

        items = data.get("items") or []
        if not items:
            continue
        description = items[0].get("ExternalDescriptionStr")
        if description:
            job["raw_description"] = description
