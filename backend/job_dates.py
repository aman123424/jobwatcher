"""
job_dates.py
============

Everything about turning a job's raw, platform-specific "posted date"
data (a different shape on almost every platform - see fetchers.py's
module docstring for the common job shape every fetch_* function
produces) into something ACTUALLY USABLE - a real, comparable Python
datetime.

WHY THIS IS ITS OWN FILE (added 2026-08-29): fetchers.py needs this
(fetch_workday's own early-stop-on-staleness logic parses these same
labels), scoring.py needs this (is_recently_posted(), the 24-hour
freshness filter), and api.py needs this too (formatting
job_posted_date for display). fetchers.py already imports FROM
scoring.py (is_relevant_title, reused to pre-filter which jobs are
worth an expensive detail-fetch) - if scoring.py also imported FROM
fetchers.py for this date logic, that's a CIRCULAR import (A imports
B, B imports A), which Python cannot resolve. Pulling the shared piece
out into its own file, with no dependency on either fetchers.py or
scoring.py, is what breaks that cycle - both of them import FROM here,
neither imports the other for this.
"""

import re
from datetime import datetime, timedelta, timezone

_WORKDAY_POSTED_ON_RE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)


def workday_posted_on_days(posted_on: str):
    """
    Parse Workday's relative "postedOn" label into an integer day
    count — "Posted Today" -> 0, "Posted Yesterday" -> 1, "Posted 5
    Days Ago" -> 5, "Posted 30+ Days Ago" -> 30. Confirmed live against
    real labels from Visa and Barclays on 2026-08-26 (including the
    "30+" form, which needed the trailing "+" handled explicitly).

    Returns None for anything that doesn't match — callers should
    treat that as "can't tell, don't use it to stop early" rather than
    assuming it means "old" or "new".
    """
    if not posted_on:
        return None
    m = _WORKDAY_POSTED_ON_RE.search(posted_on)
    if not m:
        return None
    word = m.group(1).lower()
    if word == "today":
        return 0
    if word == "yesterday":
        return 1
    return int(m.group(2))


def parse_posted_datetime(job: dict):
    """
    Turns whatever a job's "updated_at" field holds - a different raw
    shape per platform, see each fetch_* function's own docstring - into
    one real, comparable Python datetime (always timezone-aware, in
    UTC), or None when there's no usable date information at all.

    THIS IS THE ONE SHARED PLACE this parsing happens - fetchers.py's
    own fetch_workday() uses workday_posted_on_days() directly for its
    early-stop-on-staleness pagination logic, and BOTH api.py's
    job_posted_date display formatting and scoring.py's
    is_recently_posted() 24-hour filter call THIS function, rather than
    each re-implementing their own copy of "how do I read a Workday
    postedOn label" / "how do I read Amazon's date string" - two
    independent copies of that logic drifting apart over time is
    exactly the kind of bug this project has hit before (see
    PROJECT_LOG.md's Challenges section).

    Per platform:
      - Greenhouse, Lever, Ashby, SmartRecruiters, pcsx: a real ISO 8601
        timestamp with both date and time - parsed directly.
      - Workday: only a RELATIVE label ("Posted Today", "Posted 3 Days
        Ago") - turned into an APPROXIMATE datetime (today's date minus
        that many days, at THIS INSTANT's time-of-day, not the actual
        posting time - Workday's own data has no real time-of-day to
        recover). Genuinely a guess at the day, not a fact - see
        workday_posted_on_days()'s own docstring above.
      - Amazon: a day-only human string ("August 25, 2026") - no
        time-of-day in Amazon's own source data either, so this becomes
        midnight UTC on that date - also an approximation, just from a
        firmer starting fact (a real date, not a relative day-count).
      - DE Shaw: no posted-date field in the API response AT ALL - this
        always returns None for DE Shaw jobs, meaning "we genuinely
        cannot tell how old this posting is," not "it's very old" or
        "it's very new." Callers need to decide what None should mean
        for their own purposes (see is_recently_posted() in scoring.py
        for the choice made there).
      - Atlassian: a real timestamp with both date and time -
        "2026-08-18 08:11 AM" (portalJobPost.updatedDate) - but with NO
        timezone indicator anywhere in the response. Atlassian's own
        iCIMS instance doesn't say which timezone this clock is set to
        (Atlassian itself is headquartered across Sydney/San Francisco/
        Austin, so there's no single obvious guess either). Treated as
        UTC here - the same "pick the one universal reference point
        rather than guess a specific local zone" approach already used
        for Amazon's day-only dates above - meaning this is an
        approximation of the real posting instant, not a guaranteed-
        exact one, same honesty this function already applies to
        Workday/Amazon.
    """
    updated_at = job.get("updated_at")
    platform = job.get("platform")
    if not updated_at:
        return None

    if platform == "workday":
        days_old = workday_posted_on_days(updated_at)
        if days_old is None:
            return None
        return datetime.now(timezone.utc) - timedelta(days=days_old)

    if platform == "amazon":
        try:
            dt = datetime.strptime(updated_at, "%B %d, %Y")
        except ValueError:
            return None
        return dt.replace(tzinfo=timezone.utc)

    if platform == "atlassian":
        try:
            dt = datetime.strptime(updated_at, "%Y-%m-%d %I:%M %p")
        except ValueError:
            return None
        return dt.replace(tzinfo=timezone.utc)

    # Greenhouse, Lever, Ashby, SmartRecruiters, pcsx: a genuine ISO
    # 8601 timestamp. The .replace() handles "Z" (some APIs use that
    # instead of "+00:00" for UTC - both mean the same thing, but
    # fromisoformat() only understands the "+00:00" spelling).
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
