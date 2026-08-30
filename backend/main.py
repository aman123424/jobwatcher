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
    python main.py

I'd normally run this on a schedule (e.g. every 15-30 minutes) via
cron, a scheduled cloud function, or similar.
"""

import csv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from companies import TIER1_COMPANIES, TIER2_COMPANIES, CUSTOM_COMPANIES
from fetchers import FETCHERS
from scoring import score_job, is_relevant_title, is_india_location, is_recently_posted
from state import load_seen, save_seen, split_new_jobs

# main.py doesn't need to know or care which tier a company belongs
# to - "tier" is a label WE use to reason about how reliable a
# platform's data is, not something the running program branches on.
# By the time fetch_all_jobs() runs, every company is just
# (display_name, platform, slug) and FETCHERS[platform] handles the
# rest, Tier 1 or Tier 2 alike.
ALL_COMPANIES = CUSTOM_COMPANIES + TIER1_COMPANIES + TIER2_COMPANIES

MIN_SCORE = 50  #only notify for score >= 50/100.

LOG_FILE = os.path.join(os.path.dirname(__file__), "matches_log.csv")

# How many companies to fetch AT THE SAME TIME (added 2026-08-27 -
# see fetch_all_jobs()'s docstring for the full "why" of this change).
# 42 companies one-at-a-time (the original design) took 3-4 minutes,
# almost entirely spent WAITING on network responses rather than doing
# real work - exactly the situation where running several at once pays
# off. Kept well below 42 (i.e. NOT "just fetch every company at
# once") on purpose: too much concurrency risks looking like an attack
# to any one company's server if several of ITS requests happened to
# land in the same instant (Workday's pagination already fires many
# sequential requests per company - see fetch_workday - so the
# per-company request rate is unchanged by this setting; this only
# controls how many DIFFERENT companies run at once).
MAX_CONCURRENT_FETCHES = 10


def fetch_all_jobs() -> list[dict]:
    """
    Fetch every company in companies.py and collect everything into
    one flat list — but, as of 2026-08-27, up to MAX_CONCURRENT_FETCHES
    companies AT THE SAME TIME instead of one after another.

    IF YOU'RE NEW TO PYTHON, READ THIS FIRST — WHY THIS WORKS AND WHAT
    "CONCURRENT" MEANS HERE: fetching a company's jobs is almost all
    WAITING - our code sends a request, then does nothing until that
    company's server responds, which can take a second or more. Doing
    that one company at a time (the original design) means the
    program sits idle waiting on Company A before it even STARTS
    talking to Company B, even though Company B's server has nothing
    to do with Company A's and could have been contacted at the exact
    same moment. `concurrent.futures.ThreadPoolExecutor` (from
    Python's own standard library, no extra install needed) hands out
    a small pool of THREADS - independent, simultaneously-running
    "tracks" of the same program - so several companies' waiting
    happens at the same time instead of one after another. This is
    "concurrency," specifically the multi-THREADED kind: still one
    Python program, just multiple tracks of it in flight together.
    (This is safe here specifically because the shared SESSION object
    every fetch_* function uses - see fetchers.py - comes from the
    `requests` library, which documents its Session as safe to use
    from multiple threads at once.)

    HOW THE CODE BELOW ACTUALLY DOES THAT:
      - `executor.submit(fn, arg)` hands one function call off to the
        thread pool and immediately returns a "Future" - a placeholder
        object standing in for "the result of this call, once it's
        done" - without waiting for it to finish. Calling submit() in
        a loop, once per company, is what gets ALL of them started
        (up to MAX_CONCURRENT_FETCHES at once; the rest queue and start
        as earlier ones finish) rather than starting the next one only
        after the previous one completes.
      - `as_completed(futures)` then hands back each Future the MOMENT
        it finishes - in whatever order that happens to be, not
        necessarily the order they were submitted in. That's why the
        per-company progress lines below can print in a different
        order across different runs - expected, not a bug.
      - `future.result()` gets the actual return value (or re-raises
        the exception) from that one company's fetch, once it's done.

    Each company is still wrapped in its own try/except (moved into
    the small _fetch_one_company() helper below so it runs inside each
    thread), so one company's API being temporarily down doesn't stop
    the others from being checked - the same "isolate failures"
    principle fetchers.py itself uses internally, applied one level up,
    unchanged from before this concurrency change.
    """
    def fetch_one_company(company: tuple) -> list[dict]:
        display_name, platform, slug = company
        fetch_fn = FETCHERS[platform]  # look up the right function for this platform
        try:
            jobs = fetch_fn(display_name, slug)
            print(f"  {display_name:20s} ({platform:16s}): {len(jobs)} open jobs")
            return jobs
        except Exception as e:
            # A genuinely UNEXPECTED error (not the "API returned an
            # error" case, which fetch_* functions already handle
            # internally and return [] for) — e.g. a bug in our own
            # parsing code hitting a response shape we didn't expect.
            # We still don't want this to kill the whole run.
            print(f"  {display_name:20s} ({platform:16s}): FAILED - {e}")
            return []

    all_jobs = []
    # `with ... as executor:` creates the thread pool and guarantees
    # it's properly shut down afterward (even if something inside
    # raises an exception) - the same "with" pattern used everywhere
    # else in this codebase for opening files (see state.py, main.py's
    # own append_to_log() below).
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FETCHES) as executor:
        futures = [executor.submit(fetch_one_company, company) for company in ALL_COMPANIES]
        for future in as_completed(futures):
            all_jobs.extend(future.result())
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


def fetch_and_score_all() -> dict:
    """
    Runs the READ-ONLY half of the pipeline: fetch every company's
    current jobs, keep only Software-Engineer-shaped titles, and score
    every one of those against Aman's resume. Nothing here touches
    seen_jobs.json or matches_log.csv, and nothing here filters by
    score — every relevant job is included, however low it scores.

    WHY THIS IS SEPARATE FROM find_new_matches() BELOW: this is the
    shared "what's open and relevant right now" step that THREE
    different callers all need but each do something different with:
      - api.py's GET /jobs returns every job this function finds.
      - api.py's GET /jobs/best_match filters this down to score >= MIN_SCORE.
      - find_new_matches() below ALSO starts from this exact same
        list, then goes further — filtering by score AND comparing
        against past runs AND writing to disk — for GET /jobs/new and
        the command-line tool.
    Splitting it out here means all three share one implementation of
    "how do we fetch and score everything," instead of three separate
    copies of that logic that could quietly drift apart over time.

    Returns:
        {
            "all_jobs_count": 5867,      # every job fetched, before any filtering
            "relevant_jobs": [ ...job dicts, highest score first, EVERY
                                score included, not just qualifying ones... ],
        }
    """
    all_jobs = fetch_all_jobs()
    # Three independent filters, all applied before scoring: title has
    # to look like a Software Engineer role, location has to look
    # India-based (see is_india_location()'s docstring in scoring.py),
    # AND (added 2026-08-29, part of the /refresh architecture change)
    # it has to have been posted within the last 24 hours
    # (is_recently_posted() - see scoring.py for exactly how that's
    # checked per platform and its known precision limits, especially
    # for Workday and DE Shaw). This used to only exist as a per-
    # platform FETCH-efficiency trick for Workday/SmartRecruiters/pcsx
    # (skip re-enriching postings state.py already knows about) -
    # applying it HERE too, uniformly, on every platform's results
    # AFTER fetching, is what actually makes "posted within 24 hours"
    # a real guarantee across the whole system, not just an accident of
    # which platforms happened to get a fetch-time optimization.
    relevant_jobs = [
        j for j in all_jobs
        if is_relevant_title(j["title"])
        and is_india_location(j["location"])
        and is_recently_posted(j)
    ]
    scored_jobs = [score_job(j) for j in relevant_jobs]
    # Highest score first, so the strongest fits are the first thing
    # any caller (terminal output OR an API's JSON response) sees,
    # not buried at the bottom of the list.
    scored_jobs = sorted(scored_jobs, key=lambda j: -j["match_score"])

    return {
        "all_jobs_count": len(all_jobs),
        "relevant_jobs": scored_jobs,
    }


def find_new_matches() -> dict:
    """
    Builds on fetch_and_score_all() above to run the FULL, STATEFUL
    pipeline exactly once: on top of the read-only fetch+score step,
    this keeps only jobs scoring >= MIN_SCORE, compares that against
    what state.py already knows from past runs, logs any brand-new
    matches to matches_log.csv, and saves the updated "seen" set back
    to disk.

    WHY THIS FUNCTION EXISTS SEPARATELY FROM run() BELOW: this is the
    ONE place this particular (stateful, "what's NEW since last time")
    pipeline logic lives. run() (the command-line tool) calls this and
    prints a human-readable report from what it returns. api.py's GET
    /jobs/new endpoint calls this SAME function and turns what it
    returns into a JSON response instead. Neither of those two callers
    re-implements any of the filter/diff/save logic themselves — a
    future bug fix or behavior change here automatically applies to
    both the CLI and the API, instead of risking the two slowly
    drifting out of sync with each other.

    Returns a dict (Python's key -> value lookup type) with everything
    a caller might want to report, keyed by name rather than being a
    bare list, so each caller can pull out just what it needs:
        {
            "all_jobs_count": 5867,          # every job fetched, before any filtering
            "relevant_jobs_count": 714,      # after the Software-Engineer title filter
            "qualifying_jobs_count": 8,      # after the match_score >= MIN_SCORE filter
            "new_matches": [ ...job dicts, highest score first... ],
            "total_seen_count": 1042,        # size of the updated seen-jobs set
        }
    """
    fetch_results = fetch_and_score_all()
    relevant_jobs = fetch_results["relevant_jobs"]
    qualifying_jobs = [j for j in relevant_jobs if j["match_score"] >= MIN_SCORE]

    seen_keys = load_seen()
    new_matches, updated_seen = split_new_jobs(qualifying_jobs, seen_keys)
    # split_new_jobs() doesn't promise any particular order back, so
    # re-sort highest-score-first here too, same reasoning as above.
    new_matches = sorted(new_matches, key=lambda j: -j["match_score"])

    if new_matches:
        append_to_log(new_matches)
    save_seen(updated_seen)

    return {
        "all_jobs_count": fetch_results["all_jobs_count"],
        "relevant_jobs_count": len(relevant_jobs),
        "qualifying_jobs_count": len(qualifying_jobs),
        "new_matches": new_matches,
        "total_seen_count": len(updated_seen),
    }


def run() -> None:
    """
    The command-line entry point - `python main.py` calls this. All of
    the actual work happens inside find_new_matches() above; this
    function's only job is turning that result into readable terminal
    output (progress lines, a NEW MATCHES section, a final summary).
    """
    print(f"=== jobwatch run started {datetime.now(timezone.utc).isoformat()} ===")
    print(f"\nFetching current open jobs from {len(ALL_COMPANIES)} companies "
          f"({len(TIER1_COMPANIES)} Tier 1 + {len(TIER2_COMPANIES)} Tier 2 "
          f"+ {len(CUSTOM_COMPANIES)} custom)...")

    results = find_new_matches()

    print(f"\nTotal open jobs fetched across all companies: {results['all_jobs_count']}")
    print(f"Relevant (Software-Engineer-shaped titles): {results['relevant_jobs_count']}")
    print(f"Score >= {MIN_SCORE}: {results['qualifying_jobs_count']}")
    print(f"Of those, NEW since last run: {len(results['new_matches'])}")

    if results["new_matches"]:
        print(f"\n{'='*70}\nNEW MATCHES\n{'='*70}")
        for job in results["new_matches"]:
            print(f"\n[{job['match_score']}/100] {job['title']} — {job['source_company']}")
            print(f"  Location: {job['location']}  |  Seniority: {job['seniority']}")
            print(f"  {job['match_reason']}")
            print(f"  {job['url']}")
        print(f"\n(Appended to {LOG_FILE})")
    else:
        print("\nNo new qualifying matches this run.")

    print(f"\n=== run complete. {results['total_seen_count']} total jobs now tracked as 'seen'. ===")


if __name__ == "__main__":
    run()


# NEXT STEPS (not built yet, deliberately deferred):
#
# 1. NOTIFICATION CHANNEL. Right now "new matches" just print to the
#    terminal and append to a CSV. That only helps if I'm watching
#    the terminal. The next real upgrade is pushing new matches
#    somewhere I'll actually see promptly without checking manually
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
