"""
ingest.py
=========

The replacement for the old in-memory /refresh pipeline - fetches
every company's jobs (reusing fetchers.py completely unchanged),
keeps only the ones that are Software-Engineer-shaped, India-based,
and posted in the last 24 hours (reusing scoring.py's existing
resume-INDEPENDENT filters, completely unchanged), and UPSERTS each
one into the real `jobs` database table instead of a Python dict that
only lived as long as the Lambda container did.

WHY score_job() ITSELF IS DELIBERATELY NOT CALLED HERE ANYMORE: this
used to also score every job against Aman's own hardcoded resume
(RESUME_SKILLS etc. in scoring.py) before storing it - that made sense
when there was exactly one user. Now that `jobs` is a single shared
table every user reads from, storing ONE person's personalized score
on a shared row would be wrong for every other user. Personalized
matching (once built) will be computed live, per user, at read time -
see PROJECT_LOG.md / project memory for the full reasoning. This file
only ever stores resume-independent facts about a job (title,
location, description, when it was posted) - nothing here is specific
to any one person.

STILL NOT BUILT YET (a real, known gap - not silently faked): the
free-tier flow is supposed to show "tech stack required" and "years
of experience required" for every job, resume-independently. This
file currently leaves `Job.yoe` NULL and never populates `job_skills`
at all - extracting those from raw_description is genuinely separate,
not-yet-built work, not something to guess at inline here.

WHICH COMPANIES GET FETCHED (changed 2026-09-03, alongside the admin
"Add Company" feature): this file now builds the company list from the
DATABASE's `companies` table, not from companies.py's ALL_COMPANIES
directly (though every company originally came FROM there, via
seed_companies.py's one-time seed) - a company an admin adds through
the UI only ever creates a `companies` row, so fetching had to start
reading from there for a freshly-added company to ever actually show
up on the next refresh, instead of silently never being fetched at
all.
"""

from db import SessionLocal
from job_dates import parse_posted_datetime
from main import fetch_all_jobs
from models import Company, Job
from scoring import is_india_location, is_recently_posted, is_relevant_title


def ingest_relevant_jobs() -> dict:
    """
    Runs one full fetch-and-store pass. Returns a small summary dict
    (counts) rather than the jobs themselves - callers that need the
    actual stored jobs should query the `jobs` table directly (see
    api.py's rebuilt endpoints), not rely on this function's return
    value for that.
    """
    db = SessionLocal()
    try:
        # Same lookup companies.py's own display_name provides - built
        # once here (one query) rather than one query per job, since
        # every job's source_company needs this same lookup.
        company_rows = db.query(Company).all()
        companies_by_name = {c.name: c for c in company_rows}

        # The (name, platform, slug) tuple shape fetch_all_jobs() has
        # always expected (see main.py) - built from the live DB rows
        # instead of companies.py's own ALL_COMPANIES, so a company
        # added through the admin UI (a `companies` row with no
        # companies.py entry at all) gets fetched too, not just the
        # original seeded set. `.value` unwraps the Platform enum back
        # to the plain string FETCHERS is keyed by.
        company_tuples = [(c.name, c.platform.value, c.slug) for c in company_rows]
        all_jobs = fetch_all_jobs(company_tuples)
        relevant_jobs = [
            j for j in all_jobs
            if is_relevant_title(j["title"])
            and is_india_location(j["location"])
            and is_recently_posted(j)
        ]

        inserted = 0
        updated = 0
        skipped_unknown_company = 0

        for job in relevant_jobs:
            company = companies_by_name.get(job["source_company"])
            if company is None:
                # A company fetchers.py knows about but that hasn't
                # been seeded into the database yet (companies.py
                # changed since seed_companies.py last ran) - skip
                # rather than guess/crash; re-running seed_companies.py
                # is the real fix, this is just a safe fallback.
                skipped_unknown_company += 1
                continue

            posted_at = parse_posted_datetime(job)

            existing = (
                db.query(Job)
                .filter(Job.company_id == company.id, Job.external_job_id == job["job_id"])
                .first()
            )
            if existing is not None:
                existing.title = job["title"]
                existing.link = job["url"]
                existing.location = job["location"]
                existing.raw_description = job["raw_description"]
                existing.posted_at = posted_at
                updated += 1
            else:
                db.add(Job(
                    company_id=company.id,
                    external_job_id=job["job_id"],
                    title=job["title"],
                    link=job["url"],
                    location=job["location"],
                    raw_description=job["raw_description"],
                    posted_at=posted_at,
                ))
                inserted += 1

        db.commit()
        return {
            "all_jobs_count": len(all_jobs),
            "relevant_jobs_count": len(relevant_jobs),
            "inserted": inserted,
            "updated": updated,
            "skipped_unknown_company": skipped_unknown_company,
        }
    finally:
        db.close()


if __name__ == "__main__":
    result = ingest_relevant_jobs()
    print(result)
