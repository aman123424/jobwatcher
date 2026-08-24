"""
state.py
========

WHY THIS FILE NEEDS TO EXIST AT ALL:
Every time we run this program, we fetch the FULL current list of open
jobs at each company — not just "what's new since last time" (the ATS
APIs don't offer a "give me only new jobs" filter; they just return
everything currently open). If we ran this every 15 minutes and just
printed everything we got back, Aman would see the same 200 jobs
repeated every 15 minutes forever, with the 1 actually-new job buried
in there somewhere. That's useless.

So we need to remember, across runs, which jobs we've already shown
him — this is called "state" in backend engineering: information that
has to persist between separate executions of a program, as opposed to
variables that just live in memory and disappear when the script ends.

WHY A JSON FILE, AND NOT A REAL DATABASE:
For one person tracking a few thousand jobs at most, a JSON file on
disk is genuinely a reasonable choice, not a shortcut we should feel
bad about — it's simple, human-readable (you can open it and look), and
needs zero setup. The trade-off: it doesn't handle concurrent writes
safely (two copies of this script running at the exact same moment
could corrupt it) and it gets slower to load as it grows into the tens
of thousands of entries. Neither of those applies to how you'd
actually run this (one process, on a schedule, checking a few dozen
companies). If this ever grows into something with multiple users or
needs to run many instances in parallel, that's the point to switch to
a real database (e.g. SQLite is the natural next step — same "just a
file" simplicity, but handles concurrent access safely).

WHAT COUNTS AS "THE SAME JOB" ACROSS RUNS:
We use (platform, job_id) together as the unique key — not job_id
alone. WHY: job_id is only guaranteed unique WITHIN one platform, e.g.
Greenhouse's internal numbering has no relationship to Lever's. Two
different platforms could theoretically produce the same raw job_id
by coincidence. Combining platform + job_id removes that risk
entirely, for the cost of a slightly longer key.
"""

import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "seen_jobs.json")


def _job_key(job: dict) -> str:
    """Build the unique key used to identify a job across runs."""
    return f"{job['platform']}::{job['job_id']}"


def load_seen() -> set[str]:
    """
    Load the set of job keys we've already shown to Aman.

    Returns an empty set if the file doesn't exist yet (i.e. this is
    the very first run) — we treat "no state file" as "nothing seen
    yet", not as an error.
    """
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        return set(data.get("seen_job_keys", []))
    except (json.JSONDecodeError, OSError) as e:
        # If the file is somehow corrupted, we deliberately do NOT
        # crash the whole program over it — we log a warning and
        # start fresh. The downside of this choice: a corrupted state
        # file means Aman might get re-notified about jobs he's
        # already seen once. That's a mildly annoying outcome. The
        # alternative (crashing, or silently losing every future run
        # until someone manually fixes the file) is a worse one.
        print(f"[WARN] could not read state file, starting fresh: {e}")
        return set()


def save_seen(seen_keys: set[str]) -> None:
    """
    Persist the updated set of seen job keys back to disk.

    We write to a temporary file first, then rename it into place,
    rather than writing directly to seen_jobs.json. WHY: if the
    program crashes or the machine loses power midway through writing
    the real file, a direct write can leave a half-written, corrupted
    JSON file behind. Writing to a temp file and renaming is atomic on
    most filesystems — the rename either fully happens or doesn't,
    there's no "half-renamed" state — so seen_jobs.json is always
    either the old complete version or the new complete version, never
    something broken in between.
    """
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump({"seen_job_keys": sorted(seen_keys)}, f, indent=2)
    os.replace(tmp_path, STATE_FILE)


def split_new_jobs(jobs: list[dict], seen_keys: set[str]) -> tuple[list[dict], set[str]]:
    """
    Given this run's full list of currently-open jobs, split them into
    "genuinely new" vs "already seen", and return an updated seen-set
    that includes everything from this run (so next run knows about
    today's jobs too).

    Returns: (new_jobs, updated_seen_keys)
    """
    new_jobs = []
    updated_seen = set(seen_keys)  # copy, don't mutate the input

    for job in jobs:
        key = _job_key(job)
        if key not in seen_keys:
            new_jobs.append(job)
        updated_seen.add(key)  # mark seen regardless, so it's not "new" again next time

    return new_jobs, updated_seen
