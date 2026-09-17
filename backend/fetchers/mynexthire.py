"""fetchers/mynexthire.py - MyNextHire's public careers-widget API (Tier 1-shaped, reusable across companies)."""

import base64
import json

import requests

from .common import SESSION, TIMEOUT, record_fetch_failure

LIST_PATH = "/employer/careers/reqlist/get"
DETAIL_PATH = "/employer/jobs/careers"


def fetch_mynexthire(display_name: str, subdomain: str) -> list[dict]:
    """
    MyNextHire ("powered by Smaclify Technologies", per the page's own
    <title>) is a real multi-tenant ATS - every customer gets its own
    "{subdomain}.mynexthire.com" instance, all serving the exact same
    API shape. Found chasing Swiggy's careers page
    (careers.swiggy.com), which embeds swiggy.mynexthire.com in an
    iframe - the same "company's real career site is a thin wrapper
    around a shared vendor's API" pattern as pcsx/Zoho Recruit, just a
    vendor not seen in this codebase before.

    STATUS (2026-09-17): only ONE company (Swiggy) confirmed live so
    far - filed as a reusable tier anyway (not CUSTOM_COMPANIES-style
    one-off) because the vendor's OWN branding ("MyNextHire", a real
    named product, not a company-specific in-house system) and its
    genuinely multi-tenant subdomain structure make this a strong bet
    to generalize, unlike fetch_pearson's NLx backend (see that
    docstring) where reusability was actively tested and failed. Worth
    re-confirming the moment a second real company on mynexthire.com
    shows up.

    AUTH: none. A plain POST with a JSON body of exactly `{"source":
    "careers"}` - confirmed live that a GET is rejected outright (405
    Method Not Allowed) and a POST with an EMPTY body is rejected too
    (400 "Source is mandatory.") - "source" is the one required field,
    and its value doesn't seem to matter beyond being present-and-
    non-empty (matches whatever value the real embedded iframe itself
    sends via its URL's own "src=careers" query param).

    NO PAGINATION NEEDED - confirmed live this endpoint returns the
    ENTIRE open-requisition list in a single call, no `page`/`size`
    params accepted or needed (Swiggy: exactly 95 jobs, one response).
    Unlike Zoho Recruit's confirmed 200-item ceiling, no cap was hit
    here to even worry about - if a much larger company's total ever
    approaches something worth capping, that's a problem for whenever
    a company that size is actually added, not a guess made now.

    ARGUMENT FORMAT: `subdomain` is just the bare MyNextHire subdomain
    prefix - e.g. "swiggy" for swiggy.mynexthire.com - not a full
    domain or URL. Simpler than Zoho Recruit's `domain` argument
    because no company tested so far maps a custom domain onto this
    vendor (Swiggy's own public careers.swiggy.com is a SEPARATE
    wrapper site that embeds the mynexthire.com page in an iframe,
    not a custom domain FOR mynexthire.com itself - see the apply-URL
    reasoning below for why that distinction mattered).

    NO APPLY-URL FIELD IN THE LIST RESPONSE - same problem
    fetch_pearson hit, solved the same way: reverse-engineered from a
    real click, then verified live. The real page's own "Apply" button
    doesn't navigate anywhere directly - it does `window.parent.
    postMessage(url, ...)`, meant for a wrapper page (careers-
    integration.js, on Swiggy's own careers.swiggy.com) to catch and
    apply as the top-level location. Confirmed live (by monkey-
    patching postMessage before clicking a real Apply button) that the
    URL it sends is:
        https://careers.swiggy.com/#/careers?src=careers&p={base64}
    where {base64} is a JSON blob like {"pageType":"jd","reqId":28860,
    "page":"careers"}. BUT that specific URL needs knowing Swiggy's own
    separate public wrapper domain - a piece of config this fetcher
    doesn't have (and won't, unless a real second company demands it).
    Confirmed live instead that the SAME base64 payload works directly
    against the mynexthire.com subdomain itself, with no wrapper site
    needed at all:
        https://{subdomain}.mynexthire.com/employer/jobs/careers#?src=careers&p={base64}&page=careers
    - verified in a real browser, renders the correct job (title, ID,
    and full JD all matched) purely from `subdomain` and `reqId`, so
    this is genuinely reusable with only the one piece of config this
    function already takes.

    FULL DESCRIPTIONS INCLUDED FOR FREE - `jdDisplay` in the list
    response is already the complete, plain-text job description (no
    HTML markup found in it, confirmed by regex-scanning every Swiggy
    posting's jdDisplay for tag-shaped substrings - the only false
    positives were stray "<"/">" characters inside pasted Instagram
    links, not real markup) - no separate detail call needed, same as
    fetch_atlassian/fetch_pearson.

    DATE FORMAT - `approvedOn` is a real ISO 8601 timestamp WITH an
    explicit numeric UTC offset ("2026-09-09T04:43:38.697+0000", not
    "...+00:00" or "...Z") - confirmed Python's own
    datetime.fromisoformat() (3.11+) parses the bare "+0000" form
    directly, so job_dates.py's existing generic ISO8601 fallback
    branch already handles this correctly - no new branch needed,
    same situation as fetch_zoho_recruit and fetch_pearson before it.
    """
    subdomain = subdomain.strip()
    base_url = f"https://{subdomain}.mynexthire.com"
    list_url = f"{base_url}{LIST_PATH}"

    try:
        resp = SESSION.post(
            list_url,
            json={"source": "careers"},
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

    if not isinstance(data, dict) or "reqDetailsBOList" not in data:
        print(f"  [WARN] unexpected response shape from {list_url}: {data}")
        record_fetch_failure(f"unexpected response shape from {list_url}")
        return []

    jobs = []
    for p in data.get("reqDetailsBOList") or []:
        req_id = p.get("reqId")
        jobs.append({
            "source_company": display_name,
            "platform": "mynexthire",
            "job_id": str(req_id),
            "title": p.get("reqTitle", ""),
            "location": p.get("location", ""),
            "url": f"{base_url}{DETAIL_PATH}#?src=careers&p={_apply_payload(req_id)}&page=careers",
            "updated_at": p.get("approvedOn"),
            "raw_description": p.get("jdDisplay") or p.get("reqTitle", ""),
        })

    return jobs


def _apply_payload(req_id) -> str:
    """
    Builds the same base64-encoded JSON blob the real site's own
    "Apply" button sends via postMessage - see fetch_mynexthire's own
    docstring for how that was captured and verified. Only the two
    fields confirmed actually necessary are included (a fuller blob
    seen live also had empty "requester"/"customFields" placeholders
    and a "bufilter":-1 - confirmed live those aren't required, the
    minimal form below renders the identical job page).
    """
    payload = {"pageType": "jd", "reqId": req_id, "page": "careers"}
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
