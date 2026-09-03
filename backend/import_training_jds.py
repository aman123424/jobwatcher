"""
import_training_jds.py
=======================

ONE-OFF, RERUNNABLE script (same convention as seed_companies.py) that
imports Aman's hand-scored JD conversations (research/JDs data/*.md -
each file: a raw JD, then a "Claude Response:" section with a score
and written reasoning) as `training_examples` rows (see models.py) -
genuine training-data labels for the eventual resume-fit classifier,
sourced from Aman's own considered judgment (via Claude directly)
before this app's own scoring feature existed.

DELIBERATELY NOT `jobs`/`job_scores` rows (changed 2026-09-04, Aman's
own call after a first version of this script forced these into real
Job/Company rows just to satisfy JobScore's foreign key): every one of
these postings is already old/closed by the time it's reviewed here -
they don't belong in the live shared job feed at all, and don't need a
job_id, a company, or a posted_at to be useful as a training example -
just the JD text, the score, and the reasoning. See TrainingExample's
own docstring in models.py for the full architectural reasoning.

JD18 (Stripe) is DELIBERATELY SKIPPED - Claude's own response for it
never states a numeric score at all ("this is an internship... don't
apply"), and fabricating one here would inject a fake label into what
this whole pipeline exists to keep trustworthy. Score it manually
later if it should count.

Run once against the real database:
    python import_training_jds.py
NOT safely re-runnable in the sense of updating existing rows (unlike
job_scores' upsert-by-primary-key, training_examples has no natural
key to upsert on) - re-running will insert duplicates. Delete the
prior batch first (by created_at, or just don't re-run without reason).
"""

import re
from pathlib import Path

from db import SessionLocal
from models import TrainingExample, User

JD_DIR = Path(r"D:\Aman Bhaiya\Switch\Companies to Apply\research\JDs data")

# Aman's own real account - see TrainingExample's own docstring in
# models.py for why this is scoped to a specific user at all (shaped
# for a future where every user has their own resume/scoring profile,
# even though only Aman's is real right now).
ADMIN_EMAIL = "amankulwal27@gmail.com"

# Every JD file to import - JD18.md (Stripe) is deliberately absent,
# see module docstring.
JD_FILENAMES = [f"JD{n}.md" for n in range(1, 36) if n != 18]

_SCORE_RE = re.compile(r"Score:\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*%")
_RESPONSE_MARKER_RE = re.compile(r"#+\s*\*\*Claude Response:\*\*")


def parse_jd_file(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    parts = _RESPONSE_MARKER_RE.split(text, maxsplit=1)
    if len(parts) != 2:
        print(f"  SKIP {path.name}: couldn't find the Claude Response marker")
        return None

    jd_text = parts[0].split("**Job Description:**", 1)[-1].strip()
    response_text = parts[1].strip()

    score_match = _SCORE_RE.search(response_text)
    if score_match is None:
        print(f"  SKIP {path.name}: no numeric score found in the response (needs manual scoring)")
        return None
    low = int(score_match.group(1))
    high = int(score_match.group(2)) if score_match.group(2) else low
    score = round((low + high) / 2)

    return {"jd_text": jd_text, "reasoning": response_text, "score": score}


def main():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if admin is None:
            print(f"No user found with email {ADMIN_EMAIL} - aborting.")
            return

        imported = 0
        skipped = 0
        for filename in JD_FILENAMES:
            path = JD_DIR / filename
            if not path.exists():
                print(f"  SKIP {filename}: file not found")
                skipped += 1
                continue

            parsed = parse_jd_file(path)
            if parsed is None:
                skipped += 1
                continue

            db.add(TrainingExample(
                user_id=admin.id,
                jd_text=parsed["jd_text"],
                score=parsed["score"],
                reasoning=parsed["reasoning"],
            ))
            imported += 1
            print(f"  {filename}: score {parsed['score']}")

        db.commit()
        print(f"\nDone. Imported {imported}, skipped {skipped}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
