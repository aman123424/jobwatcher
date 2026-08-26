"""
companies.py
============

See the module docstring history in README.md for the general idea:
data (which companies) lives here, separate from logic (how to fetch
them, in fetchers.py).

TWO TIERS NOW:
- TIER1_COMPANIES: Greenhouse / Lever / Ashby / SmartRecruiters.
  Clean GET-based JSON APIs, no auth, well-documented, been live-
  tested by Aman and working (mostly - see fixes below).
- TIER2_COMPANIES: Workday. Needs a POST request with a 3-part
  tenant|wdN|site identifier. Genuinely less clean than Tier 1 (see
  fetch_workday()'s docstring in fetchers.py for the specific
  limitations) - built now, NOT yet live-tested by anyone, since
  Workday's domain isn't reachable from my sandbox either.

CHANGES SINCE THE FIRST LIVE RUN (2026-08-24):
Aman's first real run against Tier 1 surfaced 4 companies with wrong
data:
  - Sprinklr, RudderStack, HiLabs (Greenhouse) -> 404, wrong slug
  - Swiggy (Lever) -> 404, wrong slug
  - ServiceNow (SmartRecruiters) -> crashed the fetcher; root cause
    was a case-sensitivity bug (SmartRecruiters identifiers are
    case-sensitive; "ServiceNow" needed to be "servicenow")

Fixed here: ServiceNow's slug corrected to lowercase.
Still unresolved (excluded below until Aman sends corrected slugs):
  RudderStack, Swiggy, HiLabs (HiLabs' CSV note says "Custom Career
  Site" - it may not belong on ANY of these 5 platforms at all).
  Sprinklr's CSV entry now points to Workday instead of Greenhouse,
  but the given identifier ("sprinklr") is missing the wdN and site
  parts a real Workday URL needs - also excluded until completed.

A NOTE ON TRUST: "CONFIRMED" in the source CSV means Aman's
verification process found SOMETHING matching that platform. It does
NOT mean the identifier is guaranteed complete or correct - 4 of the
first 22 "confirmed" Tier 1 entries needed fixing after the very
first live run. Treat every new addition here with the same
skepticism until it's actually been run once successfully.

CUSTOM_COMPANIES RESEARCH PASS (2026-08-26):
Went through every "Not Fetched" company in Aman's tracker CSV,
checking each one's real career site for a callable API the same way
Qualcomm's fetch_qualcomm was originally found - live DevTools-style
capture, not guessing from a company name. Found a real, working API
for Amazon, DE Shaw, and (unexpectedly) Microsoft - Microsoft's career
site turned out to run the EXACT SAME "pcsx" vendor platform Qualcomm
does, just on a different subdomain, so fetch_qualcomm was
generalized into fetch_pcsx rather than duplicated. Several more
companies (Axis Bank/RippleHire, Pine Labs + Flipkart/TurboHire,
Siemens + Deloitte + CornerStone/CSOD) turned out to have a real API
too, but each needs one more piece only visible in an authenticated
browser session (exact POST body, a bearer token, etc.) - these went
into NEEDS_MORE_INFO with the specific blocker noted, not guessed
into working-looking code. Full company-by-company writeup of what
was checked and why is in the conversation this was researched in.
"""

TIER1_COMPANIES = [
    ("Razorpay",     "greenhouse",     "razorpaysoftwareprivatelimited"),
    ("Point72",      "greenhouse",     "point72"),
    ("Appian",       "greenhouse",     "appian"),
    ("Inmobi",       "greenhouse",     "inmobi"),
    ("Turing",       "greenhouse",     "turing"),
    ("Twilio",       "greenhouse",     "twilio"),
    ("Rubrik",       "greenhouse",     "rubrik"),
    ("GoDaddy",      "greenhouse",     "godaddy"),
    ("Groww",        "greenhouse",     "groww"),
    ("Graviton",     "greenhouse",     "gravitonresearchcapital"),
    ("SquarePoint",  "greenhouse",     "squarepointcapital"),
    ("Schrodinger",  "greenhouse",     "schrdinger"),
    ("Meesho",       "lever",          "meesho"),
    ("Sprinto",      "lever",          "Sprinto"),
    ("CRED",         "lever",          "cred"),
    ("Snowflake",    "ashby",          "snowflake"),
    ("Navi",         "ashby",          "navi"),
    ("ServiceNow",   "smartrecruiters","ServiceNow"),  # FIXED: was "ServiceNow" (wrong case)
]

# tenant_wd_site format: "tenant|wdN|site" - see fetch_workday()'s
# docstring in fetchers.py for exactly what each part means.
TIER2_COMPANIES = [
    ("Visa",         "workday", "visa|wd5|visa"),
    ("Barclays",     "workday", "barclays|wd3|external_career_site_barclays"),
    ("BrowserStack", "workday", "browserstack|wd3|external"),
    ("BlackRock",    "workday", "blackrock|wd1|blackrock_professional"),
    ("Trimble",      "workday", "trimble|wd1|trimblecareers"),
    ("MasterCard",   "workday", "mastercard|wd1|corporatecareers"),
    ("ABB",          "workday", "abb|wd3|external_career_page"),
    ("KLA",          "workday", "kla|wd1|annarbor"),
    ("Amadeus",      "workday", "amadeus|wd502|jobs"),
    ("eBay",         "workday", "ebay|wd5|tcgplayer_external_career"),
    ("APTIV",        "workday", "aptiv|wd5|aptiv_careers"),
    ("IQVIA",        "workday", "iqvia|wd1|iqvia"),
    ("PayPal",       "workday", "paypal|wd1|jobs"),
    ("Intel",        "workday", "intel|wd1|external"),
    ("Target",       "workday", "target|wd5|targetcareers"),
    ("Airbus",       "workday", "ag|wd3|Airbus"),
    ("Wells Fargo",  "workday", "wf|wd1|WellsFargoJobs"),
    ("CaterPillar",  "workday", "cat|wd5|CaterpillarCareers"),
    ("NatWest",      "workday", "rbs|wd3|RBS"),
    ("Sprinklr",     "workday", "sprinklr|wd1|careers")
]

# These CONFIRMED-in-the-CSV companies are deliberately NOT included
# above yet, because the data we have for them is incomplete or
# contradicted by a live test. Fixing these needs Aman's DevTools
# check (same method used for Tier 3 research), not a guess from me.
NEEDS_MORE_INFO = [
    # (company, platform, what's given, what's missing / wrong)
    ("RudderStack", "greenhouse", "rudderstack",
     "404 on live test - slug is wrong or it's not actually on Greenhouse"),
    ("Swiggy", "lever", "swiggy",
     "404 on live test - slug is wrong or it's not actually on Lever"),
    ("HiLabs", "unknown", "",
     "CSV note says 'Custom Career Site' - not on any Tier 1/2 platform"),

    # --- Added 2026-08-26, from the "Not Fetched" CSV research pass ---
    ("Axis Bank", "ripplehire", "axisbank.ripplehire.com, token=WIXhCuz0XRZ7H0GZCwjJ",
     "Real API confirmed live (POST .../candidate/candidatejobsearch, 7,831 real "
     "jobs seen in the response) - but the exact request couldn't be "
     "reverse-engineered blind. Tried: token/companySeq in a JSON body, "
     "form-encoded body, with session cookies from the page's own GET calls, "
     "with a Referer header - every attempt got a generic 'An unexpected error "
     "occurred' back. Needs Aman's DevTools 'Copy as cURL' on the real request "
     "so the missing piece (likely a CSRF header or WAF fingerprint check) is "
     "visible. Same vendor already flagged for Tredence - fixing one likely fixes both."),
    ("Pine Labs", "turbohire_gateway", "pinelabs.com/api/gateway/turbo-hire",
     "Endpoint confirmed real - a plain POST returns well-formed JSON that "
     "matches the live browser response exactly. But Pine Labs currently has "
     "0 open roles, so the shape of a NON-empty response (the actual job-list "
     "field name) is unverified. Safe to build against once they have live "
     "postings, or once captured from another company on this same "
     "company-hosted-gateway pattern that currently has openings."),
    ("Flipkart", "turbohire", "flipkart.turbohire.co, careerpage id 4d757ba0-3d57-448a-b82c-238ed87ac90f",
     "Real jobs confirmed rendering on the page (multiple departments, real "
     "open roles) but the actual data-fetch call never showed up in network "
     "capture - likely firing from inside a Web Worker/blob URL the monitor "
     "can't see (same blind spot hit on IBM's careers page). Blind-guessed "
     "REST paths (apis.turbohire.co/career-page/.../jobs etc.) all 404'd to "
     "the SPA's shell HTML instead of real data. Needs a real DevTools "
     "Network-tab capture, not another guess."),
    ("Siemens", "csod", "jobs.siemens.com",
     "Runs Cornerstone OnDemand's CSOD platform (confirmed by URL shape - see "
     "CornerStone below). Job results are returned already-rendered in the "
     "initial SSR HTML; no separate JSON search call was ever seen firing."),
    ("Deloitte", "csod", "apply.deloitte.com",
     "CSV's Lever slug ('deloitte') was tested live and 404'd, confirming the "
     "CSV's own 'unusual for a firm this size' note - Deloitte is not on Lever "
     "at all. Real career site runs the same Cornerstone OnDemand CSOD "
     "platform as Siemens (apply.deloitte.com/en_US/careers/SearchJobs) - "
     "same SSR-only situation, no separate JSON call found."),
    ("CornerStone", "csod", "cornerstone.csod.com",
     "This is Cornerstone OnDemand itself (the HR-software vendor, hiring for "
     "its own roles) - and it's the platform Siemens and Deloitte both run on. "
     "Confirmed a real REST namespace exists (services/x/career-site/v1/...) "
     "but calling it directly returns 'no Authorization header found' - needs "
     "a bearer token that's only visible in an authenticated browser session. "
     "One fetcher could plausibly cover all three CSOD companies above once "
     "that token requirement is understood."),
    ("Principias Systems", "unknown", "principiassystems.com",
     "The domain now resolves to a parked GoDaddy placeholder page, not a "
     "live company site at all - whatever ATS ('GreekTrust', per the CSV "
     "note) was found there before is no longer reachable this way. Worth "
     "double-checking this is even still a real, currently-operating company "
     "before spending more time on it."),
]

# This are the customs companies with their custom public API links
CUSTOM_COMPANIES = [
  ("Qualcomm", "pcsx", "careers.qualcomm.com|qualcomm.com|India"),
  # Microsoft needs the query filter (unlike Qualcomm) - a first live run
  # without one hit the 2000-job safety cap pulling EVERY open Microsoft
  # role worldwide, not just engineering ones. Multiple keywords (not
  # just "software engineer") so titles like "Backend Developer" with
  # no literal "software" in them still get caught - see fetch_pcsx's
  # docstring for the dedupe-by-job_id logic that makes this safe.
  ("Microsoft", "pcsx", "apply.careers.microsoft.com|microsoft.com|India|software,backend,frontend,full stack"),
  # NOTE: "country" must be an ISO3 code (IND), not a name - "India"
  # silently filters nothing. See fetch_amazon's docstring for how
  # that was found (loc_query looked like it worked but never did).
  ("Amazon", "amazon", "IND|software,backend,frontend,full stack"),
  ("DE Shaw", "deshaw", "deshaw.com"),
]

if __name__ == "__main__":
    VALID_TIER1 = {"greenhouse", "lever", "ashby", "smartrecruiters"}
    for name, platform, slug in TIER1_COMPANIES:
        assert platform in VALID_TIER1, f"{name}: unknown Tier 1 platform '{platform}'"
        assert slug.strip(), f"{name}: empty slug"

    for name, platform, slug in TIER2_COMPANIES:
        assert platform == "workday", f"{name}: TIER2_COMPANIES should only contain workday"
        # This exact check - "does it have 3 pipe-separated parts" -
        # is what would have caught Sprinklr/Caterpillar/Wells Fargo/
        # Media.net/Airbus automatically, instead of us finding out
        # only by reading the CSV by hand. Cheap check, real value.
        parts = slug.split("|")
        assert len(parts) == 3, f"{name}: malformed Workday slug '{slug}' (need tenant|wdN|site)"

    for name, platform, config in CUSTOM_COMPANIES:
        assert config.strip(), f"{name}: empty config"

    total = len(TIER1_COMPANIES) + len(TIER2_COMPANIES) + len(CUSTOM_COMPANIES)
    print(f"OK - {len(TIER1_COMPANIES)} Tier 1 + {len(TIER2_COMPANIES)} Tier 2 "
          f"+ {len(CUSTOM_COMPANIES)} custom = {total} companies, all valid.")
    print(f"({len(NEEDS_MORE_INFO)} companies waiting on more info - see NEEDS_MORE_INFO)")
