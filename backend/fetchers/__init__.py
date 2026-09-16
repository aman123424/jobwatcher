"""
fetchers
========

This is the part of the system that actually talks to each ATS
platform's API over the network and gets a list of open jobs back.

THE CORE IDEA — NORMALIZATION:
Greenhouse, Lever, Ashby, and SmartRecruiters are four different
companies with four different APIs. Each one names its fields
differently (Greenhouse calls a job's link "absolute_url", Lever calls
it "hostedUrl", etc). If we let those differences leak into the rest
of our program, every other file (scoring, state.py, main.py) would
need to know about all four shapes — messy, and painful to extend.

So every fetch_* function in this package has the SAME job: call the
API, then translate whatever it returns into one common shape (a
plain Python dict) that looks identical no matter which platform it
came from:

    {
        "source_company": "Razorpay",     # from companies.py, not the API
        "platform": "greenhouse",
        "job_id": "12345",                # unique within that platform
        "title": "Software Engineer II",
        "location": "Bengaluru, India",
        "url": "https://job-boards.greenhouse.io/.../jobs/12345",
        "updated_at": "2026-08-20T09:15:00",   # ISO 8601 string, or None
        "raw_description": "...",         # plain text, used for scoring
    }

This pattern — "adapter functions that normalize different sources
into one shape" — is genuinely useful backend design, not just
specific to this project. You'll see the same idea called an "adapter"
or "translator" layer in a lot of real systems that talk to multiple
external APIs.

WHY EACH FUNCTION CATCHES ITS OWN ERRORS:
If Razorpay's API is briefly down, we still want the other companies
to be checked. So each fetch_* function catches its own exceptions and
returns an empty list on failure, rather than letting one bad company
crash the whole run. main.py additionally logs WHICH company failed,
so failures are visible, not silently swallowed.

WHY A PACKAGE, NOT ONE 1500-LINE FILE - REORGANIZED 2026-09-06: this
used to be a single fetchers.py holding 9 unrelated platform
integrations (Greenhouse, Lever, Ashby, SmartRecruiters, Workday,
pcsx, Amazon, DE Shaw, Atlassian, TalentBrew) end to end. Genuinely
unrelated platforms sharing one file meant scrolling past Workday's
pagination quirks to find Amazon's date-parsing logic, and every
platform's own docstring cross-referenced line numbers in the SAME
giant file rather than naming a specific, findable module. Split into
one file per platform (this package) plus common.py for the small
amount of infrastructure more than one of them actually shares
(the HTTP session, safe-request wrappers, the freshness-window
constant, the multi-keyword dedupe helper) - nothing else moved to
common.py "just in case", per this project's own stated preference for
avoiding premature abstraction.

Every name external code already imports from this package (FETCHERS,
and fetch_workday for test.py's own manual smoke test) is re-exported
below, so `from fetchers import FETCHERS` and `from fetchers import
fetch_workday` keep working completely unchanged - this reorganization
is invisible to every other file in the project.
"""

from .amazon import fetch_amazon
from .ashby import fetch_ashby
from .atlassian import fetch_atlassian
from .deshaw import fetch_deshaw
from .goldman_sachs import fetch_goldman_sachs
from .greenhouse import fetch_greenhouse
from .lever import fetch_lever
from .oracle_cloud import fetch_oracle_cloud
from .pcsx import fetch_pcsx
from .pearson import fetch_pearson
from .smartrecruiters import fetch_smartrecruiters
from .talentbrew import fetch_talentbrew
from .workday import fetch_workday
from .zoho_recruit import fetch_zoho_recruit

FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
    "oracle_cloud": fetch_oracle_cloud,
    "pcsx": fetch_pcsx,
    "amazon": fetch_amazon,
    "deshaw": fetch_deshaw,
    "atlassian": fetch_atlassian,
    "talentbrew": fetch_talentbrew,
    "goldman_sachs": fetch_goldman_sachs,
    "zoho_recruit": fetch_zoho_recruit,
    "pearson": fetch_pearson,
}

__all__ = [
    "FETCHERS",
    "fetch_greenhouse", "fetch_lever", "fetch_ashby", "fetch_smartrecruiters",
    "fetch_workday", "fetch_oracle_cloud", "fetch_pcsx", "fetch_amazon", "fetch_deshaw",
    "fetch_atlassian", "fetch_talentbrew", "fetch_goldman_sachs", "fetch_zoho_recruit", "fetch_pearson",
]
