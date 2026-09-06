"""
fetchers/common.py
===================

Shared infrastructure every platform module in this package builds on:
the HTTP session, safe-request wrappers, and the two small helpers
(freshness window, multi-keyword dedupe) more than one platform needs.

Nothing platform-specific lives here - if only ONE fetcher needs a
helper (e.g. pcsx's epoch-seconds conversion, Lever's millisecond
timestamp conversion), it stays defined in that platform's own module
instead of being pulled in here "just in case" something else needs it
later. See PROJECT_LOG.md / this package's own __init__.py docstring
for the full "why a package, not one 1500-line file" reasoning.
"""

import requests

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
    out of, like DE Shaw's Next.js buildId, or TalentBrew's whole
    search-results page). Returns the raw response text on success, or
    None on any failure.
    """
    try:
        resp = SESSION.get(url, timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"  [WARN] request failed for {url}: {e}")
        return None


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
#
# Shared by smartrecruiters, workday, pcsx, and amazon - each platform
# module imports this rather than redefining its own copy.
FRESHNESS_WINDOW_DAYS = 2


def _merge_dedupe_by_job_id(list_of_job_lists):
    """
    SHARED HELPER used by fetch_pcsx, fetch_amazon, and fetch_talentbrew
    (all three search a company's job board once PER keyword —
    "software", "backend", "frontend", "full stack" — because a single
    keyword risks missing real titles like "Backend Developer" that
    don't contain the literal word "software"). This function takes all
    of those separate keyword-search results and combines them into one
    clean list with no duplicates.

    WHY DUPLICATES HAPPEN: the SAME real job can match more than one
    keyword search. A posting titled "Full Stack Software Engineer"
    would show up in BOTH the "software" search results AND the "full
    stack" search results — it's one real job, but without this step
    it would get added to our list twice, and later scored twice too.

    HOW THE DEDUPE ACTUALLY WORKS (a common Python trick worth
    understanding): a Python dict (short for "dictionary" — a
    collection of key -> value pairs, like a lookup table) can only
    ever hold ONE value for a given key. If you assign to a key that
    already exists, it just overwrites the old value — it does NOT
    create a second entry. So here, we use each job's "job_id" as the
    dict key: the first time we see a particular job_id we store it,
    and if we see that exact same job_id again later (because a
    different keyword search also matched it), we overwrite it with
    an identical copy of itself. Either way, only one copy survives.
    `.values()` at the end then hands back just the dict's values (the
    job dicts themselves) as a plain list, throwing away the job_id
    keys we only needed temporarily for the deduping.

    list_of_job_lists is a list of lists, e.g.
        [ [job, job, job], [job, job], [job] ]
    (one inner list per keyword searched) — flattened here into one.
    """
    jobs_by_id = {}
    for one_keyword_results in list_of_job_lists:
        for job in one_keyword_results:
            jobs_by_id[job["job_id"]] = job
    return list(jobs_by_id.values())
