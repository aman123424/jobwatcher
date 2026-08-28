"""
api.py
======

A thin FastAPI wrapper around the exact same job-finding logic in
main.py. This file adds NO new business logic of its own — every
endpoint below just calls a function already defined in main.py and
turns what it returns into JSON, so something other than a terminal (a
browser, a scheduled cloud job, a phone shortcut, a frontend app, etc.)
can trigger a run and get the results back over HTTP.

IF YOU'RE NEW TO PYTHON / FastAPI, READ THIS FIRST:
FastAPI is a library for building web APIs. The core ideas used below:
  - `@app.get("/jobs")` is a DECORATOR (the @ syntax) that registers
    the function right under it as the code to run whenever someone
    sends an HTTP GET request to that URL path. This is how FastAPI
    knows which Python function handles which URL — nothing calls
    get_all_relevant_jobs() directly anywhere in this file; FastAPI
    calls it for you whenever a matching request comes in.
  - A "Pydantic" class like JobMatch below (BaseModel) is a DATA SHAPE
    definition — it says exactly what fields a JobMatch has and what
    type each one is. FastAPI uses this for two things automatically:
    turning the JobMatch objects we return into JSON, and generating
    the interactive /docs page mentioned below.

THREE ENDPOINTS, EACH BUILT ON THE SAME UNDERLYING FETCH:
  - GET /jobs             every Software-Engineer-shaped job found,
                           at ANY match score (no cutoff at all).
  - GET /jobs/best_match   the same, narrowed to match_score >= MIN_SCORE
                           (Aman's stated bar - currently 50).
  - GET /jobs/new          narrowed further still: only jobs that
                           weren't already returned by a PAST call to
                           this endpoint (or a past `python main.py`
                           run) - see that endpoint's own docstring
                           below for why it behaves differently from
                           the other two.
/jobs and /jobs/best_match are both plain read-only snapshots of
what's open right now - calling either one twice in a row returns the
same jobs again (as long as nothing changed on the company side), and
neither one writes anything to disk. This is safe because every job
fetchers.py returns is already recent by construction (see
fetchers.py's FRESHNESS_WINDOW_DAYS) - there's no need for a separate
"is this within the last 24 hours" filter here, the underlying fetch
already only reaches back a couple of days at most on every platform
where that's possible to guarantee (Workday, SmartRecruiters, Amazon).

WHAT "NO AUTH FOR NOW" MEANS: this API has no login, no API key, no
access control of any kind — anyone who can reach this server's URL
can call any endpoint below and see your job matches. That's a
deliberate, temporary choice for local/personal use, not an oversight
— if this is ever deployed somewhere reachable by anyone other than
you, add authentication before doing that.

RUN IT:
    uvicorn api:app --reload
Then open http://127.0.0.1:8000/docs in a browser — FastAPI
auto-generates an interactive page there where you can try any
endpoint with one click, no curl/Postman/frontend needed.

`--reload` restarts the server automatically whenever you save a
change to any of these files — convenient while developing, but drop
it for any real/production run.
"""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from pydantic import BaseModel

from main import MIN_SCORE, fetch_and_score_all, find_new_matches
from fetchers import _workday_posted_on_days

app = FastAPI(
    title="jobwatch API",
    description="Returns Software-Engineer job postings scored against Aman's resume.",
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


def _normalize_posted_date(updated_at, platform: str) -> str | None:
    """
    Turns whatever fetch_pcsx/fetch_amazon/etc. put in a job's
    "updated_at" field (see fetchers.py's module docstring for the
    common job shape, and each fetch_* function's own docstring for
    exactly what THAT platform puts there) into one consistent,
    human-readable string in the style "27 Aug, 11pm" - or, when the
    source data only ever has a date and no time-of-day at all
    (Workday, Amazon), just "27 Aug" with no time part rather than
    making up a fake one. Returns None when there's no date
    information whatsoever (DE Shaw).

    WHY THIS NEEDS TO KNOW `platform`: the three raw shapes below
    (a real ISO timestamp, Workday's relative text, Amazon's day-only
    text) look nothing alike, and guessing which one we're looking at
    from the text alone risks silently mis-parsing one as another. We
    already know which platform a job came from (every job dict carries
    a "platform" key - see fetchers.py), so we use that to go straight
    to the right parsing method instead of guessing.
    """
    if not updated_at:
        return None

    if platform == "workday":
        # Workday gives a RELATIVE label ("Posted Today", "Posted 3
        # Days Ago"), never an absolute date. _workday_posted_on_days()
        # is the exact same parser fetch_workday itself uses for its
        # early-stop-on-staleness logic (see fetchers.py) - reused
        # here rather than parsing this same text a second, different
        # way. Turns the label into a day-count, which we subtract
        # from today's date to get an APPROXIMATE calendar date. This
        # is genuinely an approximation, not a fact: "Posted Today"
        # could mean 5 minutes ago or 20 hours ago, and Workday's own
        # data can't tell us which - that's exactly why there's no
        # time-of-day in the result for Workday jobs, only a date.
        days_old = _workday_posted_on_days(updated_at)
        if days_old is None:
            return None
        approx_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        return f"{approx_date.day} {approx_date.strftime('%b')}"

    if platform == "amazon":
        # Amazon gives a day-only human string like "August 25, 2026" -
        # there's no time-of-day anywhere in Amazon's own source data,
        # so (same as Workday above) the result here has a date only.
        try:
            dt = datetime.strptime(updated_at, "%B %d, %Y")
        except ValueError:
            return None  # unparseable - better to show nothing than a wrong date
        return f"{dt.day} {dt.strftime('%b')}"

    # Every other platform (Greenhouse, Lever, Ashby, SmartRecruiters,
    # pcsx) gives a genuine ISO 8601 timestamp WITH a real time - e.g.
    # "2026-08-24T22:19:40+00:00". datetime.fromisoformat() parses that
    # directly (the .replace() handles the "Z" some APIs use instead of
    # "+00:00" - both mean UTC, but fromisoformat() only understands
    # the "+00:00" spelling).
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None

    # Shift to IST before formatting, so the hour shown is the hour
    # Aman would actually see on his own clock right now.
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
        # `.get("updated_at")` rather than `["updated_at"]` as a small
        # defensive habit: every fetch_* function in fetchers.py DOES
        # set this key today (DE Shaw's is always explicitly None, not
        # missing - see fetch_deshaw), but `.get()` quietly returns
        # None instead of crashing this whole request if that ever
        # stopped being true for some future platform.
        job_posted_date=_normalize_posted_date(job.get("updated_at"), job["platform"]),
    )


@app.get("/jobs", response_model=list[JobMatch])
def get_all_relevant_jobs():
    """
    Fetches every company right now and returns EVERY Software-
    Engineer-shaped job found, at any match score — no cutoff, and no
    comparison against past calls (read-only, no side effects, calling
    this repeatedly is always safe).

    Same "this can take a few minutes" note as every endpoint here
    applies (see the module docstring above) - it's a live fetch
    across every company each time, not a cached/stored list.
    """
    results = fetch_and_score_all()
    return [_to_job_match(job) for job in results["relevant_jobs"]]


@app.get("/jobs/best_match", response_model=list[JobMatch])
def get_best_match_jobs():
    """
    Same live fetch as GET /jobs above, narrowed down to only jobs
    scoring >= MIN_SCORE (Aman's stated bar, currently 50 - see
    MIN_SCORE in main.py). Also read-only, no side effects, safe to
    call repeatedly.
    """
    results = fetch_and_score_all()
    qualifying_jobs = [j for j in results["relevant_jobs"] if j["match_score"] >= MIN_SCORE]
    return [_to_job_match(job) for job in qualifying_jobs]


@app.get("/jobs/new", response_model=list[JobMatch])
def get_new_jobs():
    """
    Runs the full jobwatch pipeline right now — fetch every company,
    score every relevant job, compare against what's already been seen
    — and returns just the NEW qualifying matches found on THIS call.

    IMPORTANT — THIS ONE IS DIFFERENT FROM /jobs AND /jobs/best_match
    ABOVE: those two are plain read-only snapshots; this one has real
    side effects, same as running `python main.py` once does - it
    appends any new matches to matches_log.csv and updates
    seen_jobs.json. That means calling this endpoint twice in a row
    will normally return an empty list [] the second time — not a bug,
    the same jobs just aren't "new" anymore. Use /jobs or
    /jobs/best_match instead if you just want "what's currently open,"
    without that history-tracking behavior.
    """
    results = find_new_matches()
    return [_to_job_match(job) for job in results["new_matches"]]
