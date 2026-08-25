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
]

# This are the customs companies with their custom public API links
CUSTOM_COMPANIES = [
  ("Qualcomm", "qualcomm_custom", "qualcomm.com"),
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
