"""
api.py
======

A thin FastAPI wrapper around the exact same job-finding logic in
main.py. This file adds very little new business logic of its own —
every endpoint below calls a function already defined in main.py and
turns what it returns into JSON, so something other than a terminal (a
browser, a scheduled cloud job, a phone shortcut, a frontend app, etc.)
can trigger a run and get the results back over HTTP.

IF YOU'RE NEW TO PYTHON / FastAPI, READ THIS FIRST:
FastAPI is a library for building web APIs. The core ideas used below:
  - `@app.get("/jobs")` / `@app.post("/refresh")` are DECORATORS (the @
    syntax) that register the function right under them as the code to
    run whenever someone sends a matching HTTP request. This is how
    FastAPI knows which Python function handles which URL — nothing
    calls get_all_relevant_jobs() directly anywhere in this file;
    FastAPI calls it for you whenever a matching request comes in.
  - A "Pydantic" class like JobMatch or JobsResponse below (BaseModel)
    is a DATA SHAPE definition — it says exactly what fields something
    has and what type each one is. FastAPI uses this for two things
    automatically: turning the objects we return into JSON, and
    generating the interactive /docs page mentioned below.

REWRITTEN 2026-08-29 - A REAL ARCHITECTURE CHANGE, NOT JUST A TWEAK:
Every endpoint used to trigger its OWN full live fetch across every
company, every single call - meaning /jobs and /jobs/best_match could
each take 1-4+ minutes, and calling either one twice in a row meant
paying that cost twice for (usually) the same answer. Aman's own
explicit design instead: fetching is now a separate, deliberately
TRIGGERED action (POST /refresh), and reading is now CHEAP - GET /jobs
and GET /jobs/best_match just serve whatever /refresh last found,
stored in a plain in-memory cache (_cached_jobs below), until the next
/refresh call replaces it.

THREE ENDPOINTS NOW:
  - POST /refresh          fetch every company live RIGHT NOW (jobs
                            posted in the last 24 hours only - see
                            scoring.py's is_recently_posted()), score
                            them, and REPLACE the stored cache with the
                            result. This is the ONLY endpoint that
                            actually hits the network. Can take a few
                            minutes, same as every live fetch always
                            has here.
  - GET /jobs               returns whatever /refresh last stored — no
                            new fetch, near-instant, every relevant job
                            at any score.
  - GET /jobs/best_match    same stored data, narrowed to
                            match_score >= MIN_SCORE. Also no new fetch.

REMOVED 2026-08-29: GET /jobs/new (the old stateful "what's new since
last time" endpoint, backed by seen_jobs.json/matches_log.csv) has been
deleted entirely - that behavior will eventually be rebuilt as a
frontend-side workaround on top of the /refresh cache above, not as a
fourth backend endpoint. Nothing currently calls find_new_matches() in
main.py; that function itself was intentionally left alone in main.py
in case it's reused for that later.

/jobs and /jobs/best_match now return `{"updated_at": ..., "jobs":
[...]}` (a JobsResponse - see below), not a bare JSON array like
before - mirroring the exact `{updatedAt, jobs}` shape Aman specified
for the internal cache, so a caller always knows how stale what it's
looking at is. If /refresh has never been called yet (a fresh server
start), both read endpoints return `{"updated_at": None, "jobs": []}`
rather than erroring - there's nothing broken about "nobody's
refreshed yet," it just means there's nothing to show.

AUTH (added 2026-09-02): real registration/login now exists - see
auth_routes.py (POST /auth/register, POST /auth/login, both issuing a
JWT) and auth.py (password hashing, JWT creation/verification,
get_current_user). Deliberately NO email-verification gate anywhere
yet - every new account starts with `email_verified=False` and
nothing checks that flag before allowing registration, login, or
(eventually) any other feature - there's no email-sending service
wired up yet to let anyone actually complete verification, so gating
on it would just lock everyone out. This is Aman's own explicit call,
not an oversight - revisit once a real email service exists.

The job-related endpoints below (/refresh, /jobs, /jobs/best_match)
are STILL fully open, no login required at all - multi-user auth
exists now at the account level, but nothing has been wired up yet to
actually scope job data per-user (that's the next piece: `user_jobs`
already exists in the database - see models.py - for exactly this,
just not read from or written to by any endpoint yet).

RUN IT:
    uvicorn api:app --reload
Then open http://127.0.0.1:8000/docs in a browser — FastAPI
auto-generates an interactive page there where you can try any
endpoint with one click, no curl/Postman/frontend needed.

`--reload` restarts the server automatically whenever you save a
change to any of these files — convenient while developing, but drop
it for any real/production run. ONE IMPORTANT CONSEQUENCE OF --reload
SPECIFICALLY WITH THIS NEW CACHE: every reload starts a BRAND NEW
Python process, and _cached_jobs below is just a plain variable living
in that process's memory - a reload WIPES the cache (back to
"nobody's refreshed yet"), the same way restarting the server does.
This is expected, not a bug - if you edit a file and the server
reloads, you'll need to call /refresh again before /jobs has anything
to show.
"""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth_routes import router as auth_router
from main import MIN_SCORE, fetch_and_score_all
from job_dates import parse_posted_datetime

app = FastAPI(
    title="jobwatch API",
    description="Returns Software-Engineer job postings scored against Aman's resume.",
)

# Mounts POST /auth/register and POST /auth/login (see auth_routes.py)
# - kept in their own file/router rather than defined directly here,
# since account/auth concerns and job-fetching concerns are genuinely
# separate things that don't need to grow in the same file forever.
app.include_router(auth_router)

# CORS ("Cross-Origin Resource Sharing"): by default, a browser blocks
# a page running on one origin (e.g. the frontend dev server at
# http://localhost:5173) from calling an API on a DIFFERENT origin
# (this server, http://127.0.0.1:8000) - different port counts as a
# different origin even on the same machine. Without this, every fetch()
# call the frontend makes here would fail silently with a CORS error
# visible only in the browser console, not as a normal HTTP error.
# Restricted to the frontend's own known dev-server origins (both
# "localhost" and "127.0.0.1" - browsers treat them as different
# origins even though they resolve to the same machine) rather than "*"
# (allow everyone) - reasonable for a personal tool with no auth (see
# this file's own "NO AUTH FOR NOW" note above): no reason to let ANY
# website that happens to load in your browser call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # The deployed frontend (S3 + CloudFront, added 2026-08-31) -
        # see PROJECT_LOG.md for the deployment details. Both dev and
        # deployed origins are kept here rather than replacing one with
        # the other, since local development against this same live
        # Lambda backend should keep working too.
        "https://d1gn3ykg202ojt.cloudfront.net",
        # The custom domain (added 2026-08-31) - a browser's CORS check
        # is based on the exact Origin it's actually loaded from, so
        # this needs to be listed explicitly even though it's the SAME
        # CloudFront distribution as the entry above - the plain
        # .cloudfront.net domain still works too and is kept here
        # rather than removed, in case it's ever used directly again.
        "https://jobwatcher.mykave.in",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class JobMatch(BaseModel):
    """
    The shape of ONE job in every endpoint's JSON response below.

    Field names here are "snake_case" (words_separated_by_underscores)
    on purpose, matching the style used everywhere else in this
    codebase (company_name, job_id, etc. in fetchers.py) — the API's
    JSON keys will come out exactly as written here: company_name,
    job_id, job_title, job_link, match_score, match_reason,
    is_strong_match, job_posted_date.

    A NOTE ON job_posted_date SPECIFICALLY: every platform gives us
    posted-date info in a DIFFERENT raw format (see fetchers.py's
    module docstring for the common job shape every fetch_* function
    produces, and _normalize_posted_date() below for exactly how each
    one is handled) — this field is the NORMALIZED result of that,
    always in the fixed style "27 Aug, 11pm" when we know both the
    date and the time, or just "27 Aug" when the source platform only
    ever gives us a date with no time-of-day (Workday, Amazon — see
    _normalize_posted_date()'s docstring for why). It's typed
    `str | None` (rather than a real date/datetime) because DE Shaw's
    data has no posted-date information at all — `| None` here means
    "either some text, or the Python value None (meaning 'no value at
    all')," which is what tells Pydantic/FastAPI this field is allowed
    to be missing for DE Shaw jobs specifically, instead of erroring.
    """
    company_name: str
    job_id: str
    job_title: str
    job_link: str
    match_score: int
    match_reason: str
    is_strong_match: bool
    job_posted_date: str | None


class JobsResponse(BaseModel):
    """
    The shape POST /refresh, GET /jobs, and GET /jobs/best_match all
    return - matches Aman's own specified cache structure ({updatedAt,
    jobs}) directly, just spelled `updated_at` (snake_case) for
    consistency with every other field name in this API.

    updated_at is None specifically when /refresh has never been
    called since this server process started (see this file's module
    docstring for why a --reload restart resets this) - `datetime |
    None` tells Pydantic/FastAPI that's a valid, expected state, not
    an error.
    """
    updated_at: datetime | None
    jobs: list[JobMatch]


# The score at and above which scoring.py's own _build_reason()
# function (see scoring.py) already labels a match "Strong match" in
# its match_reason text. Reusing that exact number here rather than
# inventing a second, different threshold that could end up disagreeing
# with the wording already inside match_reason for the same job.
STRONG_MATCH_THRESHOLD = 55

# India Standard Time is a fixed +5:30 offset from UTC year-round (it
# never observes daylight saving), so building one directly like this
# is all that's needed - no need for a timezone-database library just
# for this one, unchanging offset. `timezone(...)` (from the datetime
# module) builds a fixed-offset timezone object; passing THAT to a
# datetime's .astimezone() is the standard, correct way to convert a
# timezone-aware datetime from one clock to another - used below to
# show posted times the way Aman would actually read his own clock,
# not in UTC.
_IST = timezone(timedelta(hours=5, minutes=30))

# THE CACHE. A plain module-level dict - Python's simplest possible
# form of "state that outlives a single function call" (see state.py's
# own module docstring for the same "a plain file/variable is
# genuinely fine for one person's use, not a shortcut to feel bad
# about" reasoning, applied here to memory instead of disk). Holds
# whatever POST /refresh below most recently found; GET /jobs and GET
# /jobs/best_match only ever READ this, never trigger a fetch
# themselves. Starts empty - "nobody's refreshed since this server
# started" is a normal, valid state, not an error condition.
_cached_jobs = {
    "updated_at": None,   # a real Python datetime once set, or None
    "jobs": [],            # list of the internal job dicts fetch_and_score_all() returns
}


def _normalize_posted_date(job: dict) -> str | None:
    """
    Turns a job's raw "updated_at" field into one consistent, human-
    readable string in the style "27 Aug, 11pm" - or, when the source
    platform only ever gives a date with no time-of-day (Workday,
    Amazon), just "27 Aug" with no time part rather than making up a
    fake one. Returns None when there's no date information whatsoever
    (DE Shaw).

    Uses parse_posted_datetime() (job_dates.py) to do the actual
    per-platform parsing - the SAME function scoring.py's
    is_recently_posted() 24-hour filter uses - rather than this file
    keeping its own second copy of "how do I read a Workday postedOn
    label." This function's only remaining job is FORMATTING an
    already-parsed datetime for display, not parsing it in the first
    place.
    """
    dt = parse_posted_datetime(job)
    if dt is None:
        return None

    if job["platform"] in ("workday", "amazon"):
        # Both of these only ever produce an APPROXIMATE datetime with
        # no real time-of-day (see parse_posted_datetime()'s own
        # docstring for why) - showing a hyper-specific-looking time
        # for either would be showing false precision, so these two
        # get a date-only result instead.
        return f"{dt.day} {dt.strftime('%b')}"

    # Every other platform (Greenhouse, Lever, Ashby, SmartRecruiters,
    # pcsx) gives a genuine timestamp with a real time. Shift to IST
    # before formatting, so the hour shown is the hour Aman would
    # actually see on his own clock right now.
    dt_ist = dt.astimezone(_IST)

    # dt_ist.hour is 0-23 (24-hour clock). Converting to a 12-hour
    # clock: "% 12" wraps 13->1, 14->2, ..., 23->11, but ALSO wraps
    # 12->0 - which is wrong (12pm should stay "12", not become "0").
    # "or 12" fixes exactly that one case: if the "% 12" result is 0
    # (falsy in Python), use 12 instead.
    hour_12 = dt_ist.hour % 12 or 12
    am_pm = "am" if dt_ist.hour < 12 else "pm"
    return f"{dt_ist.day} {dt_ist.strftime('%b')}, {hour_12}{am_pm}"


def _to_job_match(job: dict) -> JobMatch:
    """
    Converts one of our internal job dicts — the common shape every
    fetch_* function in fetchers.py produces, then scoring.py adds
    match_score/match_reason to (see fetchers.py's module docstring
    for the full shape) — into the JobMatch shape every endpoint below
    promises its callers. Keeping this translation in one small
    function, in one place, means the internal job-dict shape can keep
    evolving (new fields, renamed fields) without every endpoint
    needing to change — only this one function would.
    """
    return JobMatch(
        company_name=job["source_company"],
        job_id=job["job_id"],
        job_title=job["title"],
        job_link=job["url"],
        match_score=job["match_score"],
        match_reason=job["match_reason"],
        is_strong_match=job["match_score"] >= STRONG_MATCH_THRESHOLD,
        job_posted_date=_normalize_posted_date(job),
    )


@app.post("/refresh", response_model=JobsResponse)
def refresh_jobs():
    """
    THE ONLY ENDPOINT THAT ACTUALLY FETCHES ANYTHING. Runs the full
    live pipeline right now - every company, filtered to jobs posted
    in the last 24 hours (is_recently_posted() in scoring.py) AND
    India-based AND Software-Engineer-shaped, all scored - and REPLACES
    the stored cache with the result (see _cached_jobs above). GET
    /jobs and GET /jobs/best_match serve whatever this call left behind
    until the next POST /refresh.

    POST, not GET, because this has a real side effect (replacing
    server-side state) and can take a few minutes - the same "this can
    take a while" reality every live fetch in this project has always
    had, just now scoped to one explicit, deliberately-triggered
    action instead of happening on every single read.
    """
    results = fetch_and_score_all()
    _cached_jobs["updated_at"] = datetime.now(timezone.utc)
    _cached_jobs["jobs"] = results["relevant_jobs"]
    return JobsResponse(
        updated_at=_cached_jobs["updated_at"],
        jobs=[_to_job_match(job) for job in _cached_jobs["jobs"]],
    )


@app.get("/jobs", response_model=JobsResponse)
def get_all_relevant_jobs():
    """
    Returns whatever POST /refresh most recently found — every
    relevant job at any match score. Does NOT trigger a new fetch;
    near-instant, safe to call as often as you want. If /refresh has
    never been called since this server started, returns
    `{"updated_at": null, "jobs": []}` rather than erroring.
    """
    return JobsResponse(
        updated_at=_cached_jobs["updated_at"],
        jobs=[_to_job_match(job) for job in _cached_jobs["jobs"]],
    )


@app.get("/jobs/best_match", response_model=JobsResponse)
def get_best_match_jobs():
    """
    Same stored data as GET /jobs above, narrowed down to only jobs
    scoring >= MIN_SCORE (Aman's stated bar, currently 50 - see
    MIN_SCORE in main.py). Also reads from the cache only - no new
    fetch, safe to call repeatedly.
    """
    qualifying_jobs = [j for j in _cached_jobs["jobs"] if j["match_score"] >= MIN_SCORE]
    return JobsResponse(
        updated_at=_cached_jobs["updated_at"],
        jobs=[_to_job_match(job) for job in qualifying_jobs],
    )


