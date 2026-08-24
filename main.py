"""
main.py
=======

This is the file you actually run. It ties together the other four
files into one end-to-end pass:

    companies.py  -->  fetchers.py  -->  scoring.py  -->  state.py
    (who to check)     (get current      (is it a        (is it NEW
                        open jobs)        good fit?)      since last
                                                           time?)

ONE FULL RUN, STEP BY STEP:
  1. For every company in companies.py, call the fetcher that matches
     its platform, and get back today's full list of open jobs there.
  2. Throw away jobs whose title isn't Software-Engineer-shaped (we
     don't care that a company also has an open Sales role).
  3. Score every remaining job against Aman's resume.
  4. Keep only jobs scoring >= MIN_SCORE (Aman's stated bar: 50/100).
  5. Compare against seen_jobs.json — jobs already shown on a previous
     run are dropped; only genuinely new ones are reported.
  6. Print the new matches, AND append them to matches_log.csv so
     there's a permanent record even after they scroll off the
     terminal (this doubles as the "notification" for now — see the
     NEXT STEPS note at the bottom of this file).
  7. Save the updated seen-set back to disk, so next run knows about
     everything that was open today.

RUN IT:
    python3 main.py

You'd normally run this on a schedule (e.g. every 15-30 minutes) via
cron, a scheduled cloud function, or similar — see README.md.
"""

import csv
import os
from datetime import datetime, timezone

from companies import TIER1_COMPANIES
from fetchers import FETCHERS
from scoring import score_job, is_relevant_title
from state import load_seen, save_seen, split_new_jobs

# main.py doesn't need to know or care which tier a company belongs
# to - "tier" is a label WE use to reason about how reliable a
# platform's data is, not something the running program branches on.
# By the time fetch_all_jobs() runs, every company is just
# (display_name, platform, slug) and FETCHERS[platform] handles the
# rest, Tier 1 or Tier 2 alike.
ALL_COMPANIES = TIER1_COMPANIES

MIN_SCORE = 50  # only notify for score >= 50/100.

LOG_FILE = os.path.join(os.path.dirname(__file__), "matches_log.csv")


def fetch_all_jobs() -> list[dict]:
    """
    Loop over every company in companies.py, call its matching
    fetcher, and collect everything into one flat list.

    Each company is wrapped in its own try/except so that one
    company's API being temporarily down doesn't stop us from
    checking the other 21. This is the same "isolate failures"
    principle fetchers.py uses internally, applied one level up.
    """
    all_jobs = []
    for display_name, platform, slug in ALL_COMPANIES:
        fetch_fn = FETCHERS[platform]  # look up the right function for this platform
        try:
            jobs = fetch_fn(display_name, slug)
            print(f"  {display_name:20s} ({platform:16s}): {len(jobs)} open jobs")
            all_jobs.extend(jobs)
        except Exception as e:
            # A genuinely UNEXPECTED error (not the "API returned an
            # error" case, which fetch_* functions already handle
            # internally and return [] for) — e.g. a bug in our own
            # parsing code hitting a response shape we didn't expect.
            # We still don't want this to kill the whole run.
            print(f"  {display_name:20s} ({platform:16s}): FAILED - {e}")
    return all_jobs


def append_to_log(new_matches: list[dict]) -> None:
    """
    Append newly-found matches to a CSV log on disk, so there's a
    durable, browsable record of everything the system has ever
    surfaced — not just whatever's currently on screen.

    We APPEND (not overwrite) so past runs' results are never lost,
    and we write the header row only if the file doesn't exist yet.
    """
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "found_at", "company", "title", "location", "platform",
                "match_score", "match_reason", "seniority", "url",
            ])
        found_at = datetime.now(timezone.utc).isoformat()
        for job in new_matches:
            writer.writerow([
                found_at, job["source_company"], job["title"], job["location"],
                job["platform"], job["match_score"], job["match_reason"],
                job["seniority"], job["url"],
            ])


def run() -> None:
    print(f"=== jobwatch run started {datetime.now(timezone.utc).isoformat()} ===")

    print(f"\nFetching current open jobs from {len(ALL_COMPANIES)} companies "
          f"({len(TIER1_COMPANIES)} Tier 1)...")
    all_jobs = fetch_all_jobs()
    print(f"\nTotal open jobs fetched across all companies: {len(all_jobs)}")

    relevant_jobs = [j for j in all_jobs if is_relevant_title(j["title"])]
    print(f"Relevant (Software-Engineer-shaped titles): {len(relevant_jobs)}")

    scored_jobs = [score_job(j) for j in relevant_jobs]
    qualifying_jobs = [j for j in scored_jobs if j["match_score"] >= MIN_SCORE]
    print(f"Score >= {MIN_SCORE}: {len(qualifying_jobs)}")

    seen_keys = load_seen()
    new_matches, updated_seen = split_new_jobs(qualifying_jobs, seen_keys)
    print(f"Of those, NEW since last run: {len(new_matches)}")

    if new_matches:
        print(f"\n{'='*70}\nNEW MATCHES\n{'='*70}")
        # Highest score first, so the strongest fits are the first
        # thing Aman sees, not buried at the bottom of the list.
        for job in sorted(new_matches, key=lambda j: -j["match_score"]):
            print(f"\n[{job['match_score']}/100] {job['title']} — {job['source_company']}")
            print(f"  Location: {job['location']}  |  Seniority: {job['seniority']}")
            print(f"  {job['match_reason']}")
            print(f"  {job['url']}")
        append_to_log(new_matches)
        print(f"\n(Appended to {LOG_FILE})")
    else:
        print("\nNo new qualifying matches this run.")

    save_seen(updated_seen)
    print(f"\n=== run complete. {len(updated_seen)} total jobs now tracked as 'seen'. ===")


if __name__ == "__main__":
    run()


# NEXT STEPS (not built yet, deliberately deferred):
#
# 1. NOTIFICATION CHANNEL. Right now "new matches" just print to the
#    terminal and append to a CSV. That only helps if you're watching
#    the terminal. The next real upgrade is pushing new matches
#    somewhere you'll actually see promptly without checking manually
#    — e.g. a Telegram bot message, an email, or a simple desktop
#    notification. This is a clean, separate next piece: it would slot
#    in right where `append_to_log(new_matches)` is called above,
#    without needing to touch fetchers.py, scoring.py, or state.py at
#    all — another benefit of keeping those concerns separated.
#
# 2. SCHEDULING. This script runs once and exits. To actually get
#    "notified within minutes of a posting," it needs to run
#    repeatedly on a schedule (cron, a scheduled cloud function, etc.)
#    rather than you remembering to run it manually.
#
# 3. TIER 2 (Workday) AND WHATEVER TIER 3 RESEARCH FINDS. Those are
#    separate fetcher functions to add to fetchers.py + FETCHERS dict,
#    following the exact same normalized-shape pattern used here —
#    the rest of the pipeline (scoring, state, main) doesn't need to
#    change at all to support a new platform.
