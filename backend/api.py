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

REWRITTEN 2026-08-29 (cache architecture), REWRITTEN AGAIN 2026-09-02
(real database, multi-user): fetching is a separate, deliberately
TRIGGERED action (POST /refresh) from reading (GET /jobs and friends).
As of 2026-09-02, /refresh no longer stores results in an in-memory
cache - it UPSERTS every relevant job straight into the real `jobs`
table in Postgres (see models.py, ingest.py). This is a genuine
architecture shift, not just a storage swap: jobs are now shared, real
rows every logged-in user reads from, and a user's relationship to a
job (saved/applied/not_interested) lives in its own `user_jobs` table,
completely separate from the job itself - see models.py's own module
docstring for the full reasoning, and PROJECT_LOG.md for the migration
story.

CURRENT ENDPOINTS:
  - POST /auth/register, POST /auth/login    account creation and
                            login (see auth_routes.py) - both return a
                            JWT. No email-verification gate anywhere
                            yet (Aman's own explicit call - no email
                            service exists to complete verification
                            with yet); every account starts, and stays,
                            with email_verified=False until that's built.
  - POST /refresh           fetch every company live RIGHT NOW (jobs
                            posted in the last 24 hours only, India-
                            based, Software-Engineer-shaped - see
                            ingest.py), and UPSERT each one into the
                            real `jobs` table. Requires login (added
                            2026-09-02, alongside a "Refresh Jobs"
                            button on the home page) - still a
                            shared/global action affecting every
                            user's data, not scoped to whoever
                            triggered it; login just raises the bar
                            from "anyone with the URL" to "anyone with
                            an account" (see this endpoint's own
                            docstring for the real open gap this still
                            leaves - no true admin-role check yet).
  - GET /jobs                "All Jobs" - every job posted in the last
                            24 hours (or of unknown age), with THIS
                            logged-in user's own status attached where
                            one exists. Requires login.
  - GET /jobs/new            "New Jobs" - same freshness window as "All
                            Jobs", filtered to jobs this user has never
                            acted on at all (no user_jobs row). Requires
                            login.
  - GET /jobs/mine           "My Jobs" - every job this user marked
                            Applied. No time filter - stays visible
                            long after a posting ages out of "All
                            Jobs". Requires login.
  - GET /jobs/saved          "Saved Jobs" - same idea, status == saved.
                            Requires login.
  - GET /jobs/rejected       "Rejected" - status == rejected, same "no
                            time filter" treatment as mine/saved.
                            Requires login.
  - GET /jobs/archived       "Archived Jobs" - status == not_interested,
                            but UNLIKE mine/saved/rejected, still
                            time-filtered to the same 24h window as
                            "All Jobs" - a dismissed job quietly stops
                            appearing here once the posting itself ages
                            out. Requires login.
  - POST /jobs/{id}/status   sets (or changes) this user's status on
                            one job: saved, applied, not_interested, or
                            rejected - rejected is GATED, only settable
                            when the job's current status is already
                            applied (see this endpoint's own docstring).
                            Requires login.
  - POST /companies         Admin-only (see auth.py's get_current_admin
                            and models.py's User.is_admin, both added
                            2026-09-03). Adds a company to the shared
                            `companies` table - fetched starting the
                            very next POST /refresh (see ingest.py's
                            own module docstring for how that's wired).

NOT YET BUILT (real, known gaps, not silently faked):
  - tech_stack and years_experience_required are real fields in every
    job response already, but always empty/null right now - extracting
    them from raw job text is genuinely separate, not-yet-built work
    (see ingest.py's own module docstring).
  - No personalized match_score anywhere - that's the deferred paid-
    tier ML/matching feature (LangChain/LangGraph + BM25/dense hybrid
    retrieval + Cohere reranker, phased - see project memory), to be
    computed live per user once built, never stored on the shared
    `jobs` table.
  - POST /refresh itself still isn't admin-gated (still reachable by
    anyone with the URL, not just Aman specifically) - the admin-role
    concept exists now (User.is_admin, added 2026-09-03 for POST
    /companies) but was deliberately only applied there so far; see
    that endpoint's own docstring below for the still-open reasoning.

RUN IT:
    uvicorn api:app --reload
Then open http://127.0.0.1:8000/docs in a browser — FastAPI
auto-generates an interactive page there where you can try any
endpoint with one click, no curl/Postman/frontend needed.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_admin, get_current_user
from auth_routes import router as auth_router
from db import get_db
from ingest import ingest_relevant_jobs
from models import Company, Job, JobStatus, Platform, RefreshLog, User, UserJob
from scoring import REFRESH_WINDOW_HOURS

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
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


class JobOut(BaseModel):
    """
    The shape of ONE job in every jobs-listing endpoint below.

    tech_stack and years_experience_required are REAL fields in the
    response contract already, even though nothing populates them yet
    (job_skills is never written to, Job.yoe is always NULL right now
    - see ingest.py's own module docstring for why that extraction is
    genuinely separate, not-yet-built work). Shipping the field now,
    always empty/null until that's built, means the frontend can start
    being written against this exact shape today without a second
    breaking contract change later once extraction exists.

    `status` is None specifically when the current user has never
    acted on this job (no matching user_jobs row) - a real, normal
    state, not an error - see UserJob's own docstring in models.py for
    why a row only ever gets created on an actual user action.
    """
    job_id: str
    title: str
    company_name: str
    location: str | None
    link: str
    tech_stack: list[str] = []
    years_experience_required: int | None
    posted_at: str | None
    status: str | None


class JobsListResponse(BaseModel):
    jobs: list[JobOut]
    # When POST /refresh last actually ran (see models.py's RefreshLog)
    # - None only on a brand new database that's never been refreshed
    # at all. A shared, global value (same for every user, unlike each
    # job's own per-user `status`) - see _get_last_refreshed_at below.
    last_refreshed_at: str | None = None


class SetStatusRequest(BaseModel):
    status: JobStatus


class RefreshSummary(BaseModel):
    """What POST /refresh returns - counts, not the jobs themselves.
    Callers that want the actual jobs call GET /jobs separately, which
    is also where per-user status gets attached - a bare fetch/ingest
    pass has no concept of "which user" to attach status for."""
    all_jobs_count: int
    relevant_jobs_count: int
    inserted: int
    updated: int
    skipped_unknown_company: int


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


def _format_posted_at(dt: datetime | None, platform) -> str | None:
    """
    Turns a Job row's real `posted_at` column (already a proper
    Python datetime - job_dates.py's parse_posted_datetime() did the
    actual per-platform parsing back when ingest.py stored this row,
    not here) into a consistent, human-readable string in the style
    "27 Aug, 11pm" - or, when the source platform only ever gives a
    date with no real time-of-day (Workday, Amazon - see
    parse_posted_datetime()'s own docstring for why), just "27 Aug"
    with no time part rather than showing a fake one. Returns None
    when there's no date at all (DE Shaw).
    """
    if dt is None:
        return None

    if str(platform) in ("Platform.workday", "workday", "Platform.amazon", "amazon"):
        return f"{dt.day} {dt.strftime('%b')}"

    dt_ist = dt.astimezone(_IST)
    hour_12 = dt_ist.hour % 12 or 12
    am_pm = "am" if dt_ist.hour < 12 else "pm"
    return f"{dt_ist.day} {dt_ist.strftime('%b')}, {hour_12}{am_pm}"


def _format_ist_datetime(dt: datetime | None) -> str | None:
    """
    Same "how Aman would actually read his own clock" IST conversion
    as _format_posted_at above, but for a plain timestamp with no
    per-platform special-casing (there's no source platform for "when
    did /refresh last run") and WITH minutes, unlike posted_at's
    hour-only style - precision matters more here since refreshes can
    happen minutes apart on the same day, not just at different hours.
    Style: "2 Sep, 11:47pm".
    """
    if dt is None:
        return None
    dt_ist = dt.astimezone(_IST)
    hour_12 = dt_ist.hour % 12 or 12
    am_pm = "am" if dt_ist.hour < 12 else "pm"
    return f"{dt_ist.day} {dt_ist.strftime('%b')}, {hour_12}:{dt_ist.minute:02d}{am_pm}"


def _get_last_refreshed_at(db: Session) -> str | None:
    """Shared by every jobs-listing endpoint below - reads the single RefreshLog row (see models.py) so every user's page load can show "jobs last fetched at ___", not just whoever's browser happened to trigger the last refresh."""
    log = db.get(RefreshLog, 1)
    return _format_ist_datetime(log.refreshed_at) if log is not None else None


def _to_job_out(job: Job, status: JobStatus | None) -> JobOut:
    """Shared by every jobs-listing endpoint below - one place that turns a Job row (plus this specific user's status, if any) into the response shape, so the four endpoints below can't quietly drift into returning different shapes for the same underlying data."""
    return JobOut(
        job_id=str(job.id),
        title=job.title,
        company_name=job.company.name,
        location=job.location,
        link=job.link,
        tech_stack=[],  # not built yet - see ingest.py's module docstring
        years_experience_required=job.yoe,
        posted_at=_format_posted_at(job.posted_at, job.company.platform),
        status=status.value if status else None,
    )


def _user_statuses_by_job_id(db: Session, user: User) -> dict:
    """One query for ALL of this user's user_jobs rows, turned into a {job_id: status} lookup - used by GET /jobs so attaching status to N jobs costs one query total, not one query per job."""
    rows = db.query(UserJob).filter(UserJob.user_id == user.id).all()
    return {row.job_id: row.status for row in rows}


@app.post("/refresh", response_model=RefreshSummary)
def refresh_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    THE ONLY ENDPOINT THAT ACTUALLY FETCHES ANYTHING. Runs the full
    live pipeline right now - every company, filtered to jobs posted
    in the last 24 hours AND India-based AND Software-Engineer-shaped
    (see ingest.py) - and UPSERTS each one into the real `jobs`
    database table (see models.py). Every job stored here is real,
    shared, and visible to every user via GET /jobs below - triggering
    a refresh is a shared/global action, not something that scopes
    results to just the user who clicked it.

    NOW REQUIRES LOGIN (changed 2026-09-02, was previously fully
    public) - Aman explicitly added a "Refresh Jobs" button to the
    logged-in home page, which reopened the original un-spammability
    concern (see PROJECT_LOG.md's cost-planning notes) in a more
    direct way than before: a public, unauthenticated trigger PLUS a
    visible button inviting clicks is worse than either alone.
    Requiring login raises the bar from "anyone with the URL" to
    "anyone with an account" - not true admin-only gating (still a
    known, accepted gap - no admin-role concept exists yet), but a
    real improvement over the fully-open endpoint this used to be.
    `user` itself is unused beyond the dependency enforcing login -
    this stays a shared action, not scoped to who triggered it.
    """
    result = ingest_relevant_jobs()

    # Upsert the single RefreshLog row (fixed id=1) so every user's
    # next GET /jobs (see _get_last_refreshed_at above) reflects this
    # run, not just whoever's browser triggered it.
    log = db.get(RefreshLog, 1)
    if log is not None:
        log.refreshed_at = datetime.now(timezone.utc)
    else:
        db.add(RefreshLog(id=1, refreshed_at=datetime.now(timezone.utc)))
    db.commit()

    return RefreshSummary(**result)


def _within_freshness_window(query):
    """
    Shared by GET /jobs and GET /jobs/archived below - both need the
    same "posted within the last 24 hours, or of unknown post time"
    condition (see ingest.py/is_recently_posted's own "unknown age
    passes the filter" reasoning - a job with no posted_at at all,
    like DE Shaw's, still shows rather than silently vanishing).
    Factored out so this condition can't quietly drift between the two
    endpoints that both need it.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=REFRESH_WINDOW_HOURS)
    return query.filter((Job.posted_at >= cutoff) | (Job.posted_at.is_(None)))


def _newest_first(query):
    """
    Shared by every job-listing endpoint below - none of them had ANY
    explicit ordering before this (FIXED 2026-09-02, a real bug Aman
    caught): Postgres was free to return rows in whatever order it
    found convenient, which meant a newly-surfaced posting from a
    refresh could land anywhere in the list, forcing a full manual
    re-scan every single time to find what was actually new. Sorting
    by `posted_at` descending means the freshest postings consistently
    surface at the top instead.

    `.nullslast()` matters specifically here: Postgres's own default
    for a DESC sort puts NULLs FIRST, not last - without this, every
    job with an unknown post time (DE Shaw - see Job.posted_at's own
    nullable reasoning) would dominate the very top of every list,
    which is the opposite of what "newest first" should mean for jobs
    we don't even know the age of.
    """
    return query.order_by(Job.posted_at.desc().nullslast())


@app.get("/jobs", response_model=JobsListResponse)
def get_all_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    "All Jobs" tab - every job posted within the last 24 hours (or of
    unknown post time), with THIS user's own status attached where one
    exists.

    Time-filtered HERE, at read time, rather than relying on
    POST /refresh to delete stale rows - this is deliberate: a row
    that ages out of this 24-hour window doesn't get deleted, it just
    stops showing up here, while still being fully intact for
    GET /jobs/mine or GET /jobs/saved below (neither of which apply
    any time filter at all) if the user already saved or applied to it.
    """
    jobs = _newest_first(_within_freshness_window(db.query(Job))).all()
    statuses = _user_statuses_by_job_id(db, user)
    return JobsListResponse(
        jobs=[_to_job_out(j, statuses.get(j.id)) for j in jobs],
        last_refreshed_at=_get_last_refreshed_at(db),
    )


@app.get("/jobs/new", response_model=JobsListResponse)
def get_new_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    "New Jobs" tab (added 2026-09-03) - jobs posted within the last 24
    hours (same freshness window as "All Jobs") that this user has
    NEVER acted on at all - no matching user_jobs row (see UserJob's
    own docstring in models.py: a missing row already means
    "unseen/no status", not a fourth status value, so this is a filter
    on absence, not on some `status = null`).

    A dedicated "still needs a decision" queue, separate from "All
    Jobs" (which shows every job regardless of status) - this one
    naturally shrinks as a job gets ANY status, the same
    disappears-once-handled behavior every other tab already gives a
    user for their own chosen status, just for "nothing chosen yet".
    """
    acted_job_ids = db.query(UserJob.job_id).filter(UserJob.user_id == user.id)
    jobs = (
        _newest_first(_within_freshness_window(db.query(Job)))
        .filter(~Job.id.in_(acted_job_ids))
        .all()
    )
    return JobsListResponse(
        jobs=[_to_job_out(j, None) for j in jobs],
        last_refreshed_at=_get_last_refreshed_at(db),
    )


@app.get("/jobs/mine", response_model=JobsListResponse)
def get_my_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """"My Jobs" tab - every job this user has marked Applied. No time filter - stays visible long after the posting itself ages out of "All Jobs", exactly as specified: saved/applied jobs persist "until the user himself decides to remove them"."""
    jobs = (
        _newest_first(db.query(Job))
        .join(UserJob, UserJob.job_id == Job.id)
        .filter(UserJob.user_id == user.id, UserJob.status == JobStatus.applied)
        .all()
    )
    return JobsListResponse(
        jobs=[_to_job_out(j, JobStatus.applied) for j in jobs],
        last_refreshed_at=_get_last_refreshed_at(db),
    )


@app.get("/jobs/saved", response_model=JobsListResponse)
def get_saved_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """"Saved Jobs" tab - same idea as GET /jobs/mine above, filtered to status == saved instead of applied."""
    jobs = (
        _newest_first(db.query(Job))
        .join(UserJob, UserJob.job_id == Job.id)
        .filter(UserJob.user_id == user.id, UserJob.status == JobStatus.saved)
        .all()
    )
    return JobsListResponse(
        jobs=[_to_job_out(j, JobStatus.saved) for j in jobs],
        last_refreshed_at=_get_last_refreshed_at(db),
    )


@app.get("/jobs/rejected", response_model=JobsListResponse)
def get_rejected_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    "Rejected" tab (added 2026-09-03) - same idea as GET /jobs/mine and
    GET /jobs/saved above, filtered to status == rejected, and same "no
    time filter" treatment - a job you actually applied to and got
    rejected from is exactly the kind of thing worth tracking long past
    its original 24-hour posting window, not something that should
    silently vanish once the posting itself ages out.
    """
    jobs = (
        _newest_first(db.query(Job))
        .join(UserJob, UserJob.job_id == Job.id)
        .filter(UserJob.user_id == user.id, UserJob.status == JobStatus.rejected)
        .all()
    )
    return JobsListResponse(
        jobs=[_to_job_out(j, JobStatus.rejected) for j in jobs],
        last_refreshed_at=_get_last_refreshed_at(db),
    )


@app.get("/jobs/archived", response_model=JobsListResponse)
def get_archived_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    "Archived Jobs" tab - jobs this user marked Not Interested. Unlike
    /jobs/mine and /jobs/saved, this ONE status-filtered tab ALSO
    applies the same 24-hour freshness window "All Jobs" uses
    (Aman's own explicit call, 2026-09-02) - a dismissed job quietly
    stops showing up here once the posting itself ages out, the same
    way it would from "All Jobs", rather than sticking around
    indefinitely the way a real Saved/Applied job intentionally does.
    The underlying user_jobs row itself is never deleted - it just
    stops matching this query once the joined job's `posted_at` falls
    outside the window, exactly the same "filter at read time, don't
    delete rows" approach GET /jobs already uses.
    """
    jobs = (
        _newest_first(_within_freshness_window(db.query(Job)))
        .join(UserJob, UserJob.job_id == Job.id)
        .filter(UserJob.user_id == user.id, UserJob.status == JobStatus.not_interested)
        .all()
    )
    return JobsListResponse(
        jobs=[_to_job_out(j, JobStatus.not_interested) for j in jobs],
        last_refreshed_at=_get_last_refreshed_at(db),
    )


@app.post("/jobs/{job_id}/status")
def set_job_status(
    job_id: str,
    payload: SetStatusRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Sets (or changes) the current user's status on one job - saved,
    applied, not_interested, or rejected. A single status field, not
    independent flags (see UserJob's own docstring in models.py) -
    marking a job Applied after it was Saved simply overwrites the
    Saved status, it doesn't keep both true at once.

    UPSERT: creates a new user_jobs row if this user has never acted
    on this job before, or updates the existing one in place if they
    have - either way there's still only ever at most one status per
    (user, job) pair.

    `rejected` is GATED (added 2026-09-03, Aman's own explicit call):
    unlike the other three statuses, which are freely settable from
    any prior state, a job can only be marked rejected if its CURRENT
    status is already `applied` - "Rejected" only makes sense for a
    job the user actually applied to, not one they only saved or
    haven't acted on at all. Enforced HERE, not just by hiding the
    button in the frontend (see JobCard.tsx) - the frontend gate is
    for a good default UX, this one is what actually stops a client
    that skips it.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    existing = (
        db.query(UserJob)
        .filter(UserJob.user_id == user.id, UserJob.job_id == job_id)
        .first()
    )

    if payload.status == JobStatus.rejected and (existing is None or existing.status != JobStatus.applied):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A job must be marked Applied before it can be marked Rejected",
        )

    if existing is not None:
        existing.status = payload.status
    else:
        db.add(UserJob(user_id=user.id, job_id=job_id, status=payload.status))
    db.commit()
    return {"job_id": job_id, "status": payload.status.value}


@app.delete("/jobs/{job_id}/status")
def clear_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Clears the current user's status on one job - the "toggle off"
    counterpart to set_job_status above, for when a status was set by
    mistake (e.g. clicking Not Interested again to undo it).

    Consistent with this schema's existing convention (see UserJob's
    docstring in models.py): "no status" is represented by the ABSENCE
    of a user_jobs row, not by some fourth "none" enum value - so
    clearing means deleting the row outright, not overwriting it.

    Idempotent: clearing a status that was never set (no row exists)
    still returns success, same as DELETE semantics for any resource
    that's already gone.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    existing = (
        db.query(UserJob)
        .filter(UserJob.user_id == user.id, UserJob.job_id == job_id)
        .first()
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
    return {"job_id": job_id, "status": None}


class CreateCompanyRequest(BaseModel):
    company_name: str
    # A real Platform enum, not a plain string - FastAPI/Pydantic
    # rejects anything that isn't one of fetchers.py's actual known
    # platforms with a clean 422 before this endpoint's own code even
    # runs. A free-text platform would let an admin create a company
    # that can NEVER be fetched (FETCHERS[platform] would KeyError
    # inside ingest.py the moment a refresh tried it) with no
    # indication anything was wrong until that crash - this closes
    # that off at the door instead.
    platform: Platform
    # The platform-specific fetch identifier - format varies a lot by
    # platform (see Company.slug's own docstring in models.py, e.g.
    # Workday's "tenant|wdN|site" vs a plain Greenhouse board slug) -
    # deliberately NOT validated here beyond "non-empty string", since
    # there's no single format that's correct across every platform.
    slug: str


class CreateCompanyResponse(BaseModel):
    id: str
    name: str


@app.post("/companies", response_model=CreateCompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: CreateCompanyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Admin-only (see get_current_admin in auth.py). Adds a new row to
    the shared `companies` table - from the NEXT POST /refresh onward,
    ingest.py builds its fetch list straight from this table (changed
    2026-09-03 specifically to make this endpoint actually work end to
    end - see ingest.py's own module docstring), so a company added
    here starts showing up in everyone's job feed on the very next
    refresh, no redeploy needed.

    `admin` itself is unused beyond the dependency enforcing the
    access check - who specifically added a company isn't tracked
    anywhere right now (a real, small gap - worth a created_by column
    if that history ever matters).
    """
    existing = db.query(Company).filter(Company.name == payload.company_name).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A company with this name already exists",
        )

    company = Company(name=payload.company_name, platform=payload.platform, slug=payload.slug)
    db.add(company)
    db.commit()
    db.refresh(company)
    return CreateCompanyResponse(id=str(company.id), name=company.name)


