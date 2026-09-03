"""
models.py
=========

The database schema, as SQLAlchemy ORM models - one Python class per
table. This is the finalized design worked out with Aman across
several conversations (see PROJECT_LOG.md / memory for the full
reasoning); this file is the concrete implementation of it.

IF YOU'RE NEW TO SQLALCHEMY, READ THIS FIRST: `Mapped[str]` and
`mapped_column(...)` together are SQLAlchemy 2.0's way of declaring
one column - `Mapped[str]` tells Python (and your editor) the
column's Python-side type, `mapped_column(...)` tells SQLAlchemy the
actual database-side details (primary key? nullable? unique? a
default?). A class inheriting from `Base` (see db.py) becomes one
real database table; each `Mapped[...]` attribute becomes one column.

THE ONE ARCHITECTURAL DECISION THAT SHAPES EVERYTHING HERE: `jobs` is
the single shared pool of postings every user reads from - fetched
once per refresh, same rows for everyone. A user's relationship to a
job (did they save it? apply? mark not interested?) is a SEPARATE
table, `UserJob`, with a row created ONLY when a user actually acts on
a job - not one row per job x every user, which would explode for no
benefit. This is what fixes the exact bug Aman caught early in this
design discussion: the first draft had `status` living directly on
`Job` itself, which would mean one job could only ever have ONE status
- shared and overwritten by whichever user touched it last, completely
wrong for a multi-user system.
"""

import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def _uuid_pk():
    """
    Shared helper for every table's primary key column - a
    Python-generated UUID (`uuid.uuid4`, evaluated once per new row
    right here in application code), not a Postgres-generated one
    (e.g. `gen_random_uuid()`), specifically so no Postgres extension
    needs to be enabled on the Supabase project just to support this -
    works identically regardless of what's enabled there.
    """
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# =============================================================================
# Enums - Python-side, but SQLAlchemy creates a matching real Postgres
# ENUM type for each one, so the database itself rejects an invalid
# value, not just application code.
# =============================================================================

class UserTier(str, enum.Enum):
    free = "free"
    paid = "paid"


class TokenPurpose(str, enum.Enum):
    """What an auth_tokens row is FOR - see AuthToken below for why
    email verification and password reset deliberately share one
    table instead of two near-identical ones."""
    email_verify = "email_verify"
    password_reset = "password_reset"


class Platform(str, enum.Enum):
    """
    Deliberately matches fetchers.py's FETCHERS dict keys EXACTLY
    (see fetchers.py) - these values are what actually gets used to
    look up which fetch_* function to call for a company, so drifting
    from those strings even slightly would silently break fetching.
    """
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    smartrecruiters = "smartrecruiters"
    workday = "workday"
    pcsx = "pcsx"
    amazon = "amazon"
    deshaw = "deshaw"
    atlassian = "atlassian"


class SkillImportance(str, enum.Enum):
    """Mirrors the Required-vs-Preferred distinction scoring.py's
    _REQUIRED_SECTION_RE / _PREFERRED_SECTION_RE already detect in raw
    job text today - this is that same signal, persisted per job
    instead of re-detected from raw text on every read."""
    required = "required"
    preferred = "preferred"


class JobStatus(str, enum.Enum):
    """The states a user can put a job into. Deliberately ONE field,
    not a separate boolean per state (e.g. is_saved AND is_applied) -
    a job has exactly one current status for a given user, and Aman
    confirmed this single-status model (rather than "saved" persisting
    independently of "applied") is what he wants.

    `rejected` (added 2026-09-03) is gated, not freely settable like
    the other three: api.py's set_job_status only allows transitioning
    a job TO rejected when its CURRENT status is already `applied` -
    "Rejected" only makes sense for a job you actually applied to.
    Toggling it back off (see api.py's clear_job_status) still clears
    to no status at all, same as every other status - no special case
    needed there."""
    saved = "saved"
    applied = "applied"
    not_interested = "not_interested"
    rejected = "rejected"


class JobScoreSource(str, enum.Enum):
    """
    Where a JobScore row's current value came from - lets a future
    training pipeline tell a real, human-verified label apart from an
    unreviewed placeholder, without needing a separate "is this
    trustworthy" column. `auto` rows are scoring.py's score_job()
    output, computed lazily the first time a job's score page is
    opened - a cheap, imperfect baseline, not a real label. `reviewed`
    means the admin has actually looked at it and saved their own
    score/reasoning (typically pasted in from asking Claude directly,
    see api.py's PUT /jobs/{id}/score) - THIS is the real, trustworthy
    training signal the eventual classifier gets trained on.
    """
    auto = "auto"
    reviewed = "reviewed"


# =============================================================================
# Tables
# =============================================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[UserTier] = mapped_column(
        default=UserTier.free, nullable=False
    )
    # Gates admin-only actions (currently just POST /companies - see
    # api.py's get_current_admin) - a real access-control flag, not a
    # UI-only convenience: the backend endpoint itself checks this, the
    # frontend button just hides for a non-admin user too so they don't
    # see a dead end. Defaults False - every account is a normal user
    # unless explicitly flipped (directly in the database; no
    # self-service "become an admin" path exists anywhere).
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Both nullable - only ever populated once a paid user uploads a
    # resume. resume_url points at the file in S3; scoring_logic is a
    # human-readable note on how their personal scoring was derived
    # (populated once the matching/ML phase exists - not built yet).
    resume_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_logic: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    auth_tokens: Mapped[list["AuthToken"]] = relationship(back_populates="user")
    user_jobs: Mapped[list["UserJob"]] = relationship(back_populates="user")
    user_skills: Mapped[list["UserSkill"]] = relationship(back_populates="user")


class AuthToken(Base):
    """
    Backs BOTH email verification and password reset - one table, one
    `purpose` column, rather than two near-identical tables. NOT a
    JWT: this is a separate mechanism from the JWT session/access
    tokens the API issues at login. A JWT is self-verifying (via its
    signature) and never touches the database at all; a row here
    exists specifically because a verification/reset link gets emailed
    out and clicked LATER - the server has to be able to check "is
    this exact token still valid and unused" against real stored
    state, which a stateless JWT can't do on its own.
    """
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(nullable=False)
    expires_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="auth_tokens")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    platform: Mapped[Platform] = mapped_column(nullable=False)
    # The platform-specific identifier fetchers.py actually needs to
    # fetch this company - a plain Greenhouse board slug for some
    # platforms, a pipe-separated compound string for others (Workday's
    # "tenant|wdN|site", pcsx's "host|domain|location|queries") - same
    # convention as the third element of every tuple in companies.py
    # today, just moved into the database. Called "slug" (Aman's own
    # term for this) even though it holds more than a simple slug for
    # some platforms.
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    # Distinguishes the original 46 hand-picked, personal-connection
    # companies from the much larger resolved-slug pool from the
    # Feashliaa/job-board-aggregator research pass (~14,800 candidates)
    # - see PROJECT_LOG.md - for whenever the planned Lambda-architecture
    # batch-layer split happens. Defaults True since every company
    # added so far falls into that first, hand-picked group.
    is_priority_company: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # A job is only guaranteed unique WITHIN one company - the
        # same conservative assumption state.py's (platform, job_id)
        # keying already made, just scoped to company_id here instead
        # of platform directly (safe either way, since company_id
        # already implies exactly one platform).
        UniqueConstraint("company_id", "external_job_id", name="uq_job_company_external_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # fetchers.py's own "job_id" field for this posting - NOT this
    # table's own primary key. Combined with company_id above via the
    # unique constraint, this is what prevents the same real-world
    # posting getting duplicated into a new row on every /refresh.
    external_job_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Years of experience required, if the posting states one -
    # resume-INDEPENDENT (same value shown to every user, free tier
    # included) - not to be confused with any future per-user
    # personalized match score, which deliberately isn't stored
    # anywhere in this schema at all (see project notes: computed live
    # at read time instead, since it's cheap and avoids a per-user x
    # per-job storage explosion).
    yoe: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posted_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped["Company"] = relationship(back_populates="jobs")
    job_skills: Mapped[list["JobSkill"]] = relationship(back_populates="job")
    user_jobs: Mapped[list["UserJob"]] = relationship(back_populates="job")


class Skill(Base):
    """
    A canonical skill dictionary - one row per distinct skill name
    ("React", "AWS", "Python", ...) - referenced by both jobs and
    users via the two junction tables below, rather than each storing
    its own free-text skill strings that might not match each other
    exactly ("React" vs "ReactJS" vs "react.js").
    """
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = _uuid_pk()
    skill_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class JobSkill(Base):
    """
    Junction: what a specific job actually requires - this is where
    "tech stack required" comes from for the free tier. `importance`
    mirrors the Required-vs-Preferred distinction scoring.py already
    detects from raw job text today (_REQUIRED_SECTION_RE /
    _PREFERRED_SECTION_RE) - persisted here instead of re-detected
    from raw_description on every single read.
    """
    __tablename__ = "job_skills"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), primary_key=True
    )
    importance: Mapped[SkillImportance] = mapped_column(nullable=False)

    job: Mapped["Job"] = relationship(back_populates="job_skills")
    skill: Mapped["Skill"] = relationship()


class UserSkill(Base):
    """
    Junction: a user's OWN skill profile - populated later by an LLM
    call against their uploaded resume (paid tier only; empty/unused
    for free-tier users, and not populated by anything yet - the
    matching/ML phase this feeds is deliberately deferred, see project
    notes). `proficiency` (1-10) is the per-USER equivalent of what
    JobSkill.importance means per-JOB - deliberately two separate
    columns on two separate junction tables rather than one shared
    "proficiency" field trying to mean both a person's skill level AND
    a job's requirement strength at once.
    """
    __tablename__ = "user_skills"
    __table_args__ = (
        CheckConstraint("proficiency >= 1 AND proficiency <= 10", name="ck_user_skill_proficiency_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), primary_key=True
    )
    proficiency: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped["User"] = relationship(back_populates="user_skills")
    skill: Mapped["Skill"] = relationship()


class UserJob(Base):
    """
    THE table that makes this a real multi-user system rather than a
    single-user tool with logins bolted on - see this file's module
    docstring for the full "why" behind this design. A row exists here
    ONLY once a user actually acts on a job (saves it, applies, or
    marks not interested) - there is deliberately no row for every
    job x every user, so a job with no row for a given user is
    implicitly "new/unseen" to them, with no wasted storage.

    This table is also what makes the 24-hour job lifecycle work
    correctly: "All Jobs" filters the `jobs` table by `posted_at`
    directly, with no reference to this table at all - but "My Jobs"
    and "Saved Jobs" join THROUGH this table with no time filter,
    so a job the user saved or applied to keeps showing up for them
    long after it's aged out of the general 24-hour feed, exactly as
    Aman specified: saved/applied jobs "stay in the database for a
    longer time (until the user himself decides to remove them)."
    """
    __tablename__ = "user_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True
    )
    status: Mapped[JobStatus] = mapped_column(nullable=False)
    status_updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="user_jobs")
    job: Mapped["Job"] = relationship(back_populates="user_jobs")


class JobScore(Base):
    """
    A resume-fit score + written reasoning for one (user, job) pair -
    added 2026-09-04 as the bootstrap-and-correct data pipeline toward
    a real trained resume-matching classifier (see project log/memory
    for the full plan). Deliberately its OWN table, per (user, job),
    same shape as UserJob - NOT a column on the shared `jobs` table,
    because a match score is inherently resume-specific: the exact
    same posting scores completely differently for two different
    people's resumes, so it can never be a fact that lives on the one
    shared Job row every user reads (the same architectural principle
    `status` already follows, see UserJob's own docstring above).

    Admin-only for now (api.py's endpoints gate on get_current_admin) -
    only Aman's own resume is behind scoring.py's RESUME_SKILLS right
    now, so a score here is only ever meaningful for his account. The
    table itself is already shaped generically per-user, though, so
    real per-user scoring (once every user has their own resume
    profile) is a data-population problem at that point, not a schema
    change.
    """
    __tablename__ = "job_scores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[JobScoreSource] = mapped_column(nullable=False)
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()
    job: Mapped["Job"] = relationship()


class TrainingExample(Base):
    """
    A standalone (JD text, score, reasoning) example for training the
    eventual resume-fit classifier - deliberately NOT a `jobs`/
    `job_scores` row. Added 2026-09-04, replacing a first attempt that
    force-fit Aman's 35 hand-scored JDs into real `Job`/`Company` rows
    just to satisfy JobScore's foreign key - the wrong shape for what
    these actually are: closed, days-old postings scored OUTSIDE the
    live app (by asking Claude directly), not real current listings
    that belong in the shared job feed. JobScore itself stays exactly
    as it was - it's still the right table for the live "score a real,
    currently-listed job" feature (JobCard's score badge ->
    JobScorePage), which genuinely needs to know WHICH job it's
    scoring. This table is for training data ONLY, never rendered as
    a job listing anywhere, never touches ingest.py/api.py's jobs
    pipeline at all - just a plain corpus for a future training script
    to read directly.
    """
    __tablename__ = "training_examples"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()


class RefreshLog(Base):
    """
    Tracks when POST /refresh last actually ran - a single row (fixed
    id=1, upserted in place every time), not one row per refresh. Only
    exists so GET /jobs and friends can tell every user "jobs were last
    fetched at ___" even on a fresh page load, before anyone in THIS
    browser session has clicked Refresh - refreshing is a shared/global
    action (see api.py), so this timestamp needs to be genuinely shared
    state in the database, not something tracked client-side per user.
    """
    __tablename__ = "refresh_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    refreshed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
