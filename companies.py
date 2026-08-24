"""
companies.py
============

See the module docstring history in README.md for the general idea:
data (which companies) lives here, separate from logic (how to fetch
them, in fetchers.py).

- TIER1_COMPANIES: Greenhouse / Lever / Ashby / SmartRecruiters.
  Clean GET-based JSON APIs, no auth, well-documented, been live-
  tested by Aman and working (mostly - see fixes below).
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
    ("ServiceNow",   "smartrecruiters","ServiceNow"),
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
    print(f"OK - {len(TIER1_COMPANIES)} Tier 1")
