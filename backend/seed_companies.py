"""
seed_companies.py
==================

One-time (but safely re-runnable) script that copies every company
from companies.py's TIER1_COMPANIES/TIER2_COMPANIES/CUSTOM_COMPANIES
into the real `companies` database table.

WHY THIS NEEDS TO EXIST AT ALL: companies.py stays the actual source
of truth for "which companies do we track" - it's still just a plain
Python file, still edited directly the same way it always has been,
NOT replaced by a database-backed admin UI (that's real extra work
with no real benefit yet, for a list Aman edits by hand himself). But
`jobs.company_id` (models.py) is a real foreign key into a `companies`
TABLE, not a free-text company name - so every company companies.py
knows about needs a matching row in the database too, kept in sync by
running this script again whenever companies.py changes (adding a new
company, changing a slug, etc.).

SAFELY RE-RUNNABLE: matches existing rows by `name` (companies.py's
own display_name, which is what `Company.name` is unique on) and
UPDATES their platform/slug in place if already present, rather than
either erroring on a duplicate or blindly inserting a second row for
the same company - running this again after editing companies.py is
the normal way to pick up changes, not a one-time-only script.

RUN IT:
    python3 seed_companies.py
"""

from db import SessionLocal
from main import ALL_COMPANIES
from models import Company, Platform


def seed_companies() -> None:
    db = SessionLocal()
    try:
        inserted = 0
        updated = 0
        for display_name, platform, slug in ALL_COMPANIES:
            existing = db.query(Company).filter(Company.name == display_name).first()
            if existing is not None:
                existing.platform = Platform(platform)
                existing.slug = slug
                updated += 1
            else:
                db.add(Company(
                    name=display_name,
                    platform=Platform(platform),
                    slug=slug,
                    # Every company in companies.py today is one of the
                    # original hand-picked, personal-connection
                    # companies - see Company.is_priority_company in
                    # models.py for what this distinguishes from (the
                    # much larger resolved-slug pool, not seeded here).
                    is_priority_company=True,
                ))
                inserted += 1

        db.commit()
        print(f"Seeded companies: {inserted} inserted, {updated} updated "
              f"(total in companies.py: {len(ALL_COMPANIES)})")
    finally:
        db.close()


if __name__ == "__main__":
    seed_companies()
