# JobWatcher — Project Log

A living record of what this project is, why it exists, and how it got
built. Updated as work continues — treat this as the place to look
first before re-deriving context from scratch, and the place to add
to as new work happens.

---

## Problem Statement

LinkedIn and Naukri show a job posting 1-2 days after it actually goes
live on the company's own career site. That gap isn't the company
posting late — it's a syndication delay: the posting has to travel
from the company's own ATS (Greenhouse, Workday, etc.) to LinkedIn via
a feed or integration that runs on its own schedule, often a daily
batch. By the time a listing shows up on LinkedIn, it may have already
been open — and collecting applicants — for a day or two.

The goal: a system that watches target companies' own career sites
directly, so a new posting is caught within minutes of going live, not
days. Notification only — not auto-apply. Aman applies manually; the
system's only job is to tell him something new appeared, scored
against his resume, before the applicant pool has had time to build up.

**Explicit scope boundary, decided early:** if a company keeps a role
internal-only or referral-portal-only before making it public, no
system watching the public career site can see that — that's a
company policy, not a data-access gap. For his closest connections,
messaging them directly to ask about openings on their team remains a
separate, faster, zero-engineering path that this tool doesn't replace.

---

## Why not just scrape LinkedIn/Naukri directly

Considered and set aside in favor of the ATS-direct approach, for a
few concrete reasons:

- LinkedIn's job search runs on an undocumented "guest" API (the same
  one third-party scrapers wrap) — no official access, no stability
  guarantee, and it changed its available filters in August 2026 with
  no notice.
- Even working perfectly, it's still syndicated data — same
  fundamental delay problem the project exists to solve.
- Polling a company's own ATS API removes the middleman entirely: if
  a job is live on the company's own board, we see it as soon as we
  next poll — no batch delay in between.

---

## Approach

1. **Build the target company list.** Started from a list of 97
   companies — a mix of large product companies and mid-size/startup
   companies, chosen specifically because Aman has close connections
   at these companies who could give a same-day referral.

2. **Classify each company by ATS platform**, since different
   platforms need completely different integration approaches.
   Greenhouse and Lever have no "search all customers" endpoint — you
   need to already know a company's specific slug/board token. Used a
   third-party open dataset (`Feashliaa/job-board-aggregator` on
   GitHub, built by scanning Common Crawl for known ATS URL patterns
   across ~95k companies) as a first-pass matcher, then manually
   sanity-checked the results — short/generic company names produced
   real false positives (e.g. "Ather" matching unrelated companies
   with "weather" in the name; "Principias Systems" matching a company
   literally named "System"). The dataset also missed some real
   matches under exact-match logic (Razorpay's actual slug is its full
   legal entity name, not "razorpay") until substring matching was
   added.

3. **Tier the platforms by engineering cost and reliability**, rather
   than treating every ATS the same:
   - **Tier 1** — Greenhouse, Lever, Ashby, SmartRecruiters. Clean,
     public, unauthenticated GET-based JSON APIs. Lowest cost, highest
     reliability.
   - **Tier 2** — Workday. Needs a POST request with a specific JSON
     body and a 3-part tenant/data-center/site identifier. More
     fragile — see Challenges below.
   - **Tier 3** — Companies using pcsx or customs ATS softwares.

---

## Architecture

**Repo restructured 2026-08-29** into `backend/` and `frontend/`
top-level folders (was a flat directory before) — see the "Repo
restructure" section below for why and how this was verified safe.
Backend is seven files now (was five before the FastAPI backend, six
after it, seven after `job_dates.py` was split out), each with one job:

| File | Responsibility |
|---|---|
| `companies.py` | Pure data — which companies, which platform, which slug/identifier. Split into `TIER1_COMPANIES`, `TIER2_COMPANIES`, `CUSTOM_COMPANIES` (one-off non-standard integrations), and `NEEDS_MORE_INFO` (flagged, not yet trustworthy enough to include). |
| `fetchers.py` | One function per platform. Each one calls that platform's API and normalizes the very different response shapes into one common job dict — `source_company`, `platform`, `job_id`, `title`, `location`, `url`, `updated_at`, `raw_description`. Everything downstream only ever sees this one shape, regardless of which platform a job came from. Also owns per-company fetching concurrency (`ThreadPoolExecutor`, 10 at once) and, for platforms confirmed sorted newest-first (Workday, SmartRecruiters), early-stop-on-staleness logic. |
| `job_dates.py` | Added 2026-08-29, split out of `fetchers.py` specifically to break a circular import (`scoring.py` needed date-parsing logic that used to live in `fetchers.py`, but `fetchers.py` already imports FROM `scoring.py`). The one shared place that turns each platform's very different raw "posted date" data into a real, comparable Python datetime — used by `fetchers.py` (Workday's early-stop pagination), `scoring.py` (the 24-hour freshness filter), and `api.py` (the human-readable `job_posted_date` display). |
| `scoring.py` | Evidence-weighted, JD-importance-aware match scoring against Aman's real resume content (rewritten 2026-08-28 - see that section above), 0-100, plus a plain-English reason. Also filters to Software-Engineer-shaped titles, India-only locations, infers rough seniority from the title, and (added 2026-08-29) filters to jobs posted within the last 24 hours (`is_recently_posted()`). |
| `state.py` | Remembers which jobs have already been shown, across runs, via a JSON file keyed on `(platform, job_id)` — used by the still-present but no-longer-API-exposed `find_new_matches()` in `main.py` (see the `/refresh` architecture section below for why it's no longer wired to an endpoint). |
| `main.py` | Runs the whole pipeline end to end. Exposes two entry points: `fetch_and_score_all()` (read-only: fetch → filter → score, no side effects) and `find_new_matches()` (built on top of the first: also filters by `MIN_SCORE`, diffs against `state.py`, logs, and saves) — both the CLI's `run()` and `api.py`'s endpoints call these same two functions rather than each having their own copy of the pipeline logic. |
| `api.py` | FastAPI backend, **rewritten 2026-08-29** around a fetch-once/read-many cache architecture — see the dedicated section below for the full design. `GET /jobs`, `GET /jobs/best_match`, `POST /refresh`. CORS enabled for the frontend's dev-server origin. No auth (deliberate, for local/personal use). |

The normalization step in `fetchers.py` is the load-bearing design
choice — it's what let three completely different pagination/response
formats (Greenhouse's `jobs` array, SmartRecruiters' paginated
`content` list, Workday's POST-based search) plug into the exact same
scoring and state-tracking logic without either of those ever needing
to know which platform a job came from.

`frontend/` (added 2026-08-29) is a React + TypeScript app built with
Vite, talking to the backend over HTTP — see "The React frontend"
section below for its structure and design.

---

## Tier 1 — status: built, live-tested, working

19 companies across Greenhouse, Lever, Ashby, and SmartRecruiters (the
19th, Ixigo, was added directly by Aman editing `companies.py` outside
a conversation with Claude — noted here since it wasn't part of any
documented research pass, just flagged so nobody's surprised finding
it undocumented elsewhere).
Live-tested against the real APIs and confirmed working after fixing
four bad slugs that had passed the automated classification but 404'd
in practice (see Challenges).

## Tier 2 — status: built, live-tested, working

Started at 18 companies, grew as Aman completed more Workday tenant
identifiers (Sprinklr, Caterpillar, Wells Fargo, Airbus, plus a new
addition, NatWest). Live-tested up to 37 real paginated requests in a
single company (APTIV, 731 jobs recovered exactly) after fixing a
pagination bug that was silently capping every large company at 40
jobs regardless of its real total — see Challenges for the full story,
since it took three attempts to find the actual cause.

As of the most recent full run: **44 companies configured** (19 Tier 1
+ 20 Tier 2 + 5 custom, after Atlassian was added 2026-08-29 - see
below). `companies.py` is the current source of truth for the exact
list — this number will keep moving as more companies get resolved out
of `NEEDS_MORE_INFO`.

## Custom companies — Amazon, Microsoft, DE Shaw added (2026-08-26)

A full research pass went through every "Not Fetched" company in
Aman's tracker CSV, checking each one's real career site for a
callable API the same live-DevTools-style way Qualcomm's fetcher was
originally found (see Challenges below) - not guessing from a company
name. Found real, working APIs for three more:

- **Amazon** - own JSON API (`amazon.jobs/en/search.json`). Real bug
  found on the first live run: `loc_query=India` LOOKED like it was
  filtering by country but was a silent no-op (real Sydney/SF/Haifa
  jobs came back anyway) - the actual filter is `country=IND` (ISO3
  code), confirmed live.
- **Microsoft** - turned out to run the EXACT SAME "pcsx" vendor
  platform Qualcomm's custom fetcher already used, just on a different
  subdomain (`apply.careers.microsoft.com` vs `careers.qualcomm.com`).
  `fetch_qualcomm` was generalized into `fetch_pcsx` rather than
  duplicated - a genuine "same vendor, different customer" finding,
  not assumed going in.
- **DE Shaw** - careers page is server-rendered Next.js with the full
  job list embedded in the page's own data payload; fetched via a
  two-step process (scrape the page's current Next.js build ID, which
  changes on every deploy, then hit its data endpoint directly).

Several more companies turned out to have a REAL API too, but each
needs one more piece only visible in an authenticated browser session
(exact POST body, a bearer token that expires hourly, etc.) - these
went into `NEEDS_MORE_INFO` with the SPECIFIC blocker noted, not
guessed into working-looking code: Axis Bank + Tredence (RippleHire -
exact request still unresolved even with a real captured payload, see
Challenges), Pine Labs + Flipkart (TurboHire - Pine Labs currently has
0 open roles so the non-empty response shape is unverified; Flipkart's
auth token expires every hour with no found way to mint a fresh one),
and Siemens + Deloitte + CornerStone (all three run the same
Cornerstone OnDemand "CSOD" platform, needs a bearer token only
visible in an authenticated session).

## Atlassian added (2026-08-29)

Aman found Atlassian's own careers listing feed himself
(`atlassian.com/endpoint/careers/listings`) and asked for it to be
checked before building. Confirmed live: a single, plain,
unauthenticated GET returns EVERY open role worldwide in one response
- 233 total postings, 27 India-related at check time - with real full
HTML description content (`responsibilities`, `qualifications`)
already included per job, no separate per-job detail call needed
(unlike Workday/SmartRecruiters/pcsx). Backed by iCIMS (the same ATS
vendor behind the still-blocked RippleHire/CornerStone entries in
`NEEDS_MORE_INFO`), but this particular endpoint needs no auth at all -
a good reminder that "same vendor" doesn't automatically mean "same
blocker."

One new wrinkle handled in `job_dates.py`: Atlassian's own timestamp
format (`"2026-08-18 08:11 AM"`) carries no timezone indicator
anywhere in the response, and Atlassian itself has no single
headquarters timezone to guess (offices split across Sydney/San
Francisco/Austin) - treated as UTC, the same "pick the one universal
reference point" approach already used for Amazon's day-only dates,
documented as an approximation rather than a guaranteed-exact time.

`fetch_atlassian()` needs no real per-company config string (the URL
never changes, there's no company-specific identifier the way every
other platform needs one) - first platform in this codebase where that
was true, handled with a placeholder config string just to satisfy
`companies.py`'s existing self-check that every `CUSTOM_COMPANIES`
entry has a non-empty config.

Verified live end-to-end through the full pipeline before considering
it done: fetched -> India + relevant-title filtered down to 3 -> ran
through `score_job()` successfully (scores reflected genuinely senior
"Principal"-level roles outside Aman's fit, not a scoring bug) -> all
modules re-imported cleanly, `companies.py`'s self-check passed at 44
total companies.

## Tier 3 — status: researched, not built

Oracle Cloud, iCIMS, SAP SuccessFactors, and five single-company
platforms (Darwinbox, RippleHire, TurboHire, GreytHR, Keka Hire) were
investigated but deliberately not built yet. Summary:

- **Oracle Cloud — ruled out entirely.** No public API (the equivalent
  endpoints are restricted to approved Oracle Marketplace partners
  only), and the public career site itself is a JavaScript app with no
  server-rendered fallback and no sitemap. Confirmed by testing
  directly against Texas Instruments' real career page.
- **iCIMS — technically possible, fundamentally different approach.**
  No JSON API; would need sitemap discovery + direct HTML parsing
  (BeautifulSoup-style), with CSS structure that varies enough between
  companies to need per-company handling. Confirmed the URL pattern
  against a real Goldman Sachs posting.
- **SAP SuccessFactors — technically possible, most complex option.**
  Two different generations of SuccessFactors career sites exist; only
  the modern "Career Site Builder" hosts are scrapable at all, and
  that requires session-cookie + CSRF-token handling, not a simple
  request.
- **The five single-company platforms** — deprioritized given the 1:1
  company-to-effort ratio; weak positive signals found for
  RippleHire/TurboHire/Darwinbox, nothing found for GreytHR/Keka Hire.

Full detail in `TIER3_RESEARCH.md`. Net effect: Tier 1 + Tier 2 cover
what they cover with real reliability; the remaining ~16 companies
across Tier 3 would each cost meaningfully more engineering effort per
company than anything built so far, with no shared pattern the way
Greenhouse or Workday had one.

---

## Freshness filtering and concurrency (2026-08-26 to 2026-08-27)

**The problem going in:** every full run fetched EVERY currently-open
job at every company, every time - fine for small boards, painfully
slow and wasteful for a company with thousands of postings (several
Workday tenants were hitting a 2000-job SAFETY CAP every run, meaning
their fetch was being arbitrarily truncated, not completing).

**Early-stop on staleness.** Confirmed LIVE (not assumed) which
platforms return results already sorted newest-first: Workday and
SmartRecruiters both do; Greenhouse, Lever, Ashby, and the `pcsx`
platform do NOT (verified and rejected before landing on Workday/
SmartRecruiters). For the two that ARE sorted, added logic to stop
paging once a page's postings are all older than a 2-day window
(`FRESHNESS_WINDOW_DAYS`) - a real speed win (Trimble: capped/2000+
jobs -> 60 real jobs in 4 seconds), but this shipped with a genuine bug
the first time: the stop check only prevented fetching the NEXT page,
but still appended the ENTIRE current page first - so one page that
was part-recent/part-stale (or a page that was 100% stale but still
got fetched because the page before it had one recent job on it) let
jobs up to 258 hours (10.8 days) old through despite the 2-day window.
Caught by Aman explicitly asking to re-test the freshness filter, not
assumed correct because the code intent was documented. Fixed by
skipping stale jobs individually AS they're found, not deciding per-
page after the fact.

**Multi-keyword search + de-dupe**, for the two custom platforms whose
search API takes a keyword (`pcsx`, Amazon): search once per keyword
("software", "backend", "frontend", "full stack" - not just "software
engineer") so a real title like "Backend Developer" doesn't get missed
for lacking the literal word "software", then merge results and drop
duplicates by job ID (a posting matching more than one keyword search
would otherwise be double-counted).

**Concurrent (multi-threaded) company fetching.** `main.py`'s
`fetch_all_jobs()` was fetching all ~40 companies one at a time -
almost entirely spent waiting on network responses, the textbook case
for concurrency. Switched to Python's `concurrent.futures.
ThreadPoolExecutor`, up to 10 companies at once. Real result: a full
run dropped from ~4 minutes to ~82 seconds.

**The concurrency rate-limit lesson (important - read before adding
more concurrency anywhere in this codebase):** the SAME "run several
requests at once" idea, applied to per-job DETAIL fetches for Qualcomm/
Microsoft (see the Microsoft-job-scoring-0 story below), triggered real
429 "too many requests" errors from Qualcomm's own server - because
unlike the company-level concurrency (10 requests spread across 10
DIFFERENT servers), this was 10 requests hammering the SAME server in
a tight burst. Tried reducing to 4 concurrent - still got errors.
Fixed only by making it fully sequential (Aman's explicit instruction:
"we can concurrently fetch for 10 different companies, but for a
single company keep it synchronous"). Verified live: 548/548 Qualcomm
job descriptions enriched successfully, zero rate-limit errors, ~7
minutes for that one company (acceptable since it runs in parallel
with everything else, not added on top).

**`pcsx` had ZERO freshness filtering at all (found 2026-08-28).** Aman
directly asked "are there really 550 relevant jobs in the last 24 hrs,
or am I missing something" after a Qualcomm run returned that many
matches. Checked: `FRESHNESS_WINDOW_DAYS` was referenced in
`fetch_workday`/`fetch_smartrecruiters`/`fetch_amazon`, but never in
`fetch_pcsx` at all - every one of Qualcomm's ~550 India postings was
getting the expensive, deliberately-sequential per-job description
enrichment above, regardless of age. Confirmed live: of 558 total India
postings, only 14 were within the 2-day freshness window: the rest
ranged up to 409 DAYS old. Unlike Workday/SmartRecruiters, `pcsx` has
no reliable sort to early-stop pagination on (`sort_by` tested live
with several values, all identical to the default) - so instead of an
early-stop, a plain post-fetch filter on the already-parsed
`postedTs`/`updated_at` field was added, which doesn't need reliable
ordering to be correct. Result: Qualcomm's fetch dropped from ~427s to
~40.7s; Microsoft (same `pcsx` platform, different subdomain) dropped
from a similarly bloated time to ~20.2s.

---

## The FastAPI backend (2026-08-27)

**Historical - superseded 2026-08-29 by the `/refresh` cache
architecture below (endpoints changed, `GET /jobs/new` removed).**
Kept here as the record of the original design. Converted the
CLI-only tool into a live HTTP API, reusing 100% of the
existing pipeline logic rather than rewriting it. `main.py` was
refactored to expose two functions the API calls directly:
`fetch_and_score_all()` (read-only: fetch + score everything, no
state-tracking side effects) and `find_new_matches()` (the original
stateful pipeline, built on top of the first). Three endpoints in a
new `api.py`:

- `GET /jobs` - every relevant job, any score, read-only.
- `GET /jobs/best_match` - same, filtered to `match_score >= MIN_SCORE`.
- `GET /jobs/new` - stateful: only jobs not already returned by a past
  call (same seen-tracking + matches_log.csv side effects as the CLI).

Response fields are `snake_case` (`company_name`, `job_id`,
`job_title`, `job_link`, `match_score`, `match_reason`,
`is_strong_match`, `job_posted_date`) per Aman's explicit call, and
`job_posted_date` is normalized to one consistent human format ("27
Aug, 11pm" when a platform gives a real time, "27 Aug" date-only when
it doesn't - Workday and Amazon never give a real time, only Greenhouse/
Lever/Ashby/SmartRecruiters/pcsx do), converted from UTC to IST so the
displayed hour matches Aman's own clock.

No auth - a deliberate, explicit, temporary choice for local/personal
use, not an oversight.

---

## Scoring system rewrite (2026-08-28)

**What triggered it:** a real Microsoft posting Aman found manually and
judged a decent fit scored 19/100 in this system, but 60/100 when Aman
fed the same job text to Claude directly and asked it to reason about
the match. Comparing the two approaches (not just accepting the gap)
surfaced real, fixable problems - none of this was guessed, each was
confirmed against real postings before being called done:

1. **Normalizing against the WHOLE resume's keyword weight was
   unrealistic** - no real posting mentions 20+ of Aman's specific
   skills, so even 2 strong core-stack matches scored near 0. Replaced
   with a calibrated "what does a strong match actually look like"
   reference score.
2. **Every matched skill counted equally, regardless of how solid the
   evidence for it is.** Every skill on Aman's resume (both the
   Technical Skills list AND anything named only in a bullet, like
   Redux/Spire.PDF which weren't tracked AT ALL before this) got
   classified as EVIDENTIAL (backed by a real resume bullet, or -
   Aman's own explicit call - a skill he confirmed as genuinely strong
   despite no bullet naming it: TDD, GitHub, GitHub Copilot, DSA, SOLID
   Principles, OOP, HTML, CSS, JavaScript) vs UNVERIFIED (sitting in
   the skills list with nothing backing it) - evidential skills count
   at full weight, unverified at half.
3. **Every matched skill counted equally regardless of how important
   THIS SPECIFIC posting treats it.** Added detection of "Required
   Qualifications" vs "Preferred Qualifications" section headers in
   real job text, weighting matches found under each differently. This
   ONLY works where real, structured description text exists -
   Workday's list API still only gives a job's own title as its
   "description," so every Workday-sourced score is meaningfully less
   trustworthy than one from a platform with real text (see the
   Workday/SmartRecruiters detail-endpoint enrichment below, which
   fixed this for real description text - Workday's own docstring in
   `fetchers.py` documents exactly what's still missing).
4. **Hard filters for years-of-experience and degree requirements** -
   regex-detects patterns like "5+ years", "5-8 years", "Master's
   degree required", and a "or equivalent experience" escape clause -
   caps the score hard (not just a discount) when a real gap is found
   with no escape clause, mirroring how Claude's own manual reasoning
   treated this as "near-automatic low score, regardless of how good
   the rest looked."

**Real bugs found DURING this rewrite, each confirmed against live
data before fixing (see Challenges for the full narrative on the two
biggest ones):**
- Plain substring keyword matching let "aws" match inside "...applicable
  local laws..." - fixed with word-boundary-safe regex matching for
  every keyword.
- The "or equivalent experience" escape clause was scoped to the whole
  document instead of the specific requirement it was meant to excuse -
  let a Twilio posting's degree-only escape clause wrongly cancel an
  unrelated "5+ years" requirement, and let ServiceNow's "Kafka or
  equivalent streaming" (nothing to do with experience at all) wrongly
  cancel an 8+ years gate.
- A title like "Senior/Staff..." was only affecting the human-readable
  caveat TEXT in match_reason, never the actual match_score - found
  because that exact Twilio posting (no explicit years number anywhere
  in its body text, only the title signal) scored 97.
- Workday's/SmartRecruiters' descriptions were enriched with real
  per-job detail-endpoint text (see the concurrency section above for
  the rate-limiting lesson learned building this) - but ONLY for jobs
  whose title already looks relevant first (`is_relevant_title()`,
  reused rather than duplicated), so a company's hundreds of Sales/HR
  postings never cost an extra request they were always going to get
  filtered out anyway.

**A real, STILL-OPEN gap found doing this comparison work, not yet
fixed:** a Schrödinger posting scored 85 almost entirely from
secondary/"Nice-to-Have" matches (React, Node.js), while its actual #1
REQUIRED skill (Python) has zero overlap with Aman's resume at all.
The scoring formula has no mechanism to penalize a big, conspicuous gap
on the most heavily-emphasized required skill - it only rewards
whatever DOES match, never flags what's glaringly absent. Left open
for a deliberate follow-up conversation rather than a rushed fix bolted
on alongside everything else that day.

**Also added the same day:** India-only location filtering
(`is_india_location()`, applied everywhere alongside the existing
title-relevance filter - most Tier 1/2 platforms fetch every country
with no location filter at all by default), and a fix for SquarePoint's
job links (their custom career-site frontend assigns its OWN internal
job IDs that share no overlap with Greenhouse's IDs for the same
postings, and there's no plain-HTTP way to resolve one to the other -
see Challenges - so SquarePoint links now point at the real listing
page instead of a URL that looks specific but silently lands on the
wrong content).

---

## The `/refresh` cache architecture rewrite (2026-08-29)

**What triggered it:** Aman shared a real `/jobs/best_match` response
where most of the jobs were from months back - a genuine surprise,
since the freshness filtering work above was believed to already
guarantee recency. Investigating surfaced the real cause: freshness
filtering had only ever been an internal FETCH-EFFICIENCY trick for
Workday/SmartRecruiters/`pcsx` (skip pages that are confirmed stale,
so a run doesn't waste time re-fetching thousands of already-seen
postings) - it was never a universal guarantee applied to
Greenhouse/Lever/Ashby/Amazon/DE Shaw results, which had no age
filtering of any kind by original design. On top of that, every
endpoint call was triggering its OWN full live fetch across every
company - `/jobs` and `/jobs/best_match` could each take 1-4+ minutes,
and calling either one twice in a row paid that full cost twice for
usually the same answer.

**Aman's own explicit redesign, given as a complete spec, not a vague
direction:** fetching becomes a separate, deliberately-triggered
action (a "refresh" button on the eventual frontend) that fetches jobs
posted within the last 24 hours across every tier and stores them,
with a timestamp, in a backend-side list; reading (`/jobs`,
`/jobs/best_match`) then only ever serves whatever that last refresh
found - no new fetching per read. Scoring happens once, at
fetch/store time, not recomputed on every read.

**What this actually required, in the order it was built:**

1. **A real 24-hour freshness filter, applied universally** -
   `is_recently_posted()`, added to `scoring.py`, checks every job
   (regardless of platform) against a 24-hour window using
   `parse_posted_datetime()`. Unknown-age jobs (DE Shaw, which has no
   posted-date field in its response at all) deliberately PASS the
   filter rather than being silently excluded - "we can't tell" is
   treated as "don't lose it," not as "assume it's old."
2. **Breaking a circular import to get there.** `scoring.py` needed
   date-parsing logic that lived in `fetchers.py` - but `fetchers.py`
   already imports `is_relevant_title` FROM `scoring.py` (used to
   pre-filter which jobs get expensive per-job detail enrichment). Two
   files each importing from the other is unresolvable in Python.
   Fixed by extracting the shared date-parsing logic
   (`parse_posted_datetime`, `workday_posted_on_days`) into a brand
   new, dependency-free `job_dates.py` that both files import FROM,
   neither importing the other for this. Each of the three touched
   modules (`job_dates.py`, `scoring.py`, `fetchers.py`) was verified
   to import cleanly independently before moving on, not assumed fine
   because the diff looked right.
3. **The cache itself, in `api.py`.** A plain module-level dict
   (`_cached_jobs = {"updated_at": None, "jobs": []}`) - the same "a
   plain variable is genuinely fine for one person's use" reasoning
   `state.py` already applies to disk, applied here to memory instead.
   `POST /refresh` is now the ONLY endpoint that touches the network:
   it runs the full pipeline, stores the result plus a fresh
   timestamp, and returns it. `GET /jobs` and `GET /jobs/best_match`
   only ever read this dict - near-instant, safe to call repeatedly,
   correctly return `{"updated_at": null, "jobs": []}` (not an error)
   before the first refresh of a server's lifetime. Both moved from
   returning a bare JSON array to `{"updated_at": ..., "jobs": [...]}`,
   mirroring Aman's own specified `{updatedAt, jobs}` shape (spelled
   snake_case for consistency with every other field name in this
   API).
4. **`GET /jobs/new` removed entirely (2026-08-29, same day, separate
   explicit instruction).** The old stateful "what's new since last
   time" endpoint (backed by `seen_jobs.json`/`matches_log.csv`) wasn't
   part of the new architecture and was deliberately cut rather than
   half-migrated - Aman's own words: he'll have this working
   client-side later, "we'll make some more changes later so that we
   get a workaround for `/jobs/new` without creating a new endpoint."
   `find_new_matches()` itself was left alone in `main.py`, unused for
   now, in case it's reused for that later. One important consequence
   worth remembering: a `--reload` restart of `uvicorn` starts a brand
   new Python process, which wipes `_cached_jobs` back to empty (same
   as a normal restart) - documented directly in `api.py`'s own module
   docstring so it isn't rediscovered as a surprise later.

**Verified live end-to-end, not just import-checked:** started a real
server, confirmed `GET /jobs` returned the empty-cache shape correctly
before any refresh; called `POST /refresh` (58.8s, HTTP 200, 10-11
jobs depending on the run); confirmed `GET /jobs` and `GET
/jobs/best_match` immediately after both returned in ~3ms (not a new
fetch) with the exact same `updated_at` timestamp as the refresh call,
and `best_match` correctly narrowed to only jobs scoring >= `MIN_SCORE`.
Re-verified the identical flow again from inside `backend/` after the
repo restructure below, to confirm the move hadn't broken anything.

---

## Repo restructure — `backend/`/`frontend/` split (2026-08-29)

Aman moved every Python file into a new `backend/` folder himself
(outside any conversation with Claude) and created an empty `frontend/`
folder alongside it, then asked for a check on whether anything needed
to change in the code as a result. Nothing did, and this was verified
rather than assumed:

- Every backend module imports every other one by bare name
  (`from job_dates import ...`), and since all of them moved together
  as a unit, that still resolves correctly regardless of which
  directory a command is run from.
- `state.py`'s `seen_jobs.json` path and `main.py`'s
  `matches_log.csv` path both already used
  `os.path.join(os.path.dirname(__file__), ...)` rather than a bare
  relative path - written that way from the start specifically so a
  change like this wouldn't break them. Confirmed live: running the
  full `/refresh` -> `/jobs` -> `/jobs/best_match` flow from inside
  `backend/` did NOT create stray copies of either file in the parent
  directory.
- No hardcoded absolute paths existed anywhere in the codebase to
  begin with (checked directly, not assumed).

**Git rename-detection, and a `.gitignore` added the same session:**
because the files were moved outside git (not via `git mv`), a plain
`git status` initially showed 10 files "deleted" at the repo root plus
an entirely new, untracked `backend/` folder - looking like unrelated
events even though nothing was actually deleted. Explained to Aman
that `git add -A` followed by `git status` lets git's own
similarity-detection recognize most of these as `renamed:` pairs
automatically (confirmed live - most files showed as clean renames;
`api.py` and the new `job_dates.py` showed as `new file` instead,
expected since their content changed substantially in the same
session, which drops below git's rename-similarity threshold). A new
root-level `.gitignore` was added at the same time, at Aman's request,
excluding `__pycache__/`, `*.pyc`, `.claude/` (Claude Code tooling
state, not project code), `matches_log.csv`, and `seen_jobs.json`
(runtime-generated state, not source) - noted for Aman that this stops
NEW copies from being picked up but doesn't itself untrack files
already committed (a `git rm --cached` step, offered but deliberately
left for Aman to run himself alongside his own commit).

---

## The React frontend (2026-08-29)

Scaffolded with Vite's `react-ts` template (not Create React App,
which is deprecated) - React 19, TypeScript 6, `oxlint` for linting.
Structured around the same DRY/SOLID principles the backend already
follows, explicitly requested rather than assumed:

| File | Responsibility |
|---|---|
| `src/api/types.ts` | `JobMatch`/`JobsResponse` types, deliberately mirroring `api.py`'s Pydantic models field-for-field - the one place a backend shape change needs to be reflected on the frontend. |
| `src/api/client.ts` | One shared `request()` helper behind three thin functions (`fetchAllJobs`, `fetchBestMatchJobs`, `refreshJobs`) - DRY: one definition of "how do we call the backend and what counts as failure," not three independent copies that could drift apart. Backend URL configurable via `VITE_API_BASE_URL` (see `.env.example`), defaulting to `uvicorn`'s own documented local address. |
| `src/hooks/useJobsData.ts` | Owns all data/view state (which view is active, the jobs list, the last-refreshed timestamp, two SEPARATE loading flags for "switching views" vs "running a real refresh" since one is near-instant and the other can take a minute, and error state) - single responsibility: DATA, not layout. |
| `src/components/RefreshBar.tsx` | The "Fetch Fresh" button and last-refreshed display. |
| `src/components/ViewToggle.tsx` | "All Relevant" / "Best Match" switch. |
| `src/components/JobCard.tsx` | One job's display - the only component that touches an individual job's fields. |
| `src/components/JobList.tsx` | Every list-level state (loading, error, no-data-yet, empty-after-refresh, real results) - keeps `JobCard` itself down to just the happy-path render of one real job. |
| `src/App.tsx` | Pure composition - wires the hook's state into the components above, no business logic of its own. |

**Backend change required to connect them:** CORS middleware added to
`api.py` (none existed before) - without it, every `fetch()` call from
the frontend's dev server (`localhost:5173`) to the backend
(`127.0.0.1:8000`) would fail as a browser-level CORS block, invisible
as a normal HTTP error. Scoped to the frontend's own known dev-server
origins specifically, not `"*"` - consistent with the API's existing
no-auth-but-not-wide-open posture.

**Verified live through an actual browser session, not just
`tsc`/lint:** `npx tsc -b` and `npm run lint` both clean (one oxlint
warning about the standard "fetch on mount" `useEffect` pattern -
confirmed a false positive for this specific idiom, silenced with a
documented inline disable rather than restructured around a
non-issue). With both dev servers running: initial load correctly
showed the empty-cache "no data yet" state; clicking "Fetch Fresh"
showed the in-flight "Fetching fresh jobs..." state, then rendered 6
real scored jobs (title, company, score badge, match reason, posted
date) after the real ~50s network refresh completed; switching to
"Best Match" correctly filtered to empty (all 6 scored below
`MIN_SCORE`) near-instantly, confirming it reads the cache rather than
re-fetching; zero console errors throughout, confirming CORS was
actually working end-to-end and not just configured.

---

## Challenges faced, and how they were actually solved

Documented in the order they happened, including the wrong turns —
the wrong guesses are as useful a record as the fixes, since the
pattern that actually worked each time was the same: stop guessing,
get one piece of concrete evidence, let that evidence decide the next
step.

### Bad slugs from the automated classification

The GitHub-dataset matcher marked Sprinklr, RudderStack, and HiLabs as
"confirmed" on Greenhouse, and Swiggy as "confirmed" on Lever. All
four 404'd on the very first live run. "Confirmed" in that dataset
meant "something matched," not "verified working" — real signal, but
not proof. HiLabs turned out to run a fully custom career site, not
any tracked platform at all. Fix: pull the bad entries out until real
slugs are found via direct DevTools verification, rather than trust
automated matching a second time.

### ServiceNow crash — wrong diagnosis, then the real one

First live run against SmartRecruiters crashed with
`'str' object has no attribute 'get'`. First guess: SmartRecruiters
identifiers are case-sensitive, and the stored slug had the wrong
case. Aman tested the exact URL directly and proved that guess wrong —
mixed case worked fine. The real bug, visible only once Aman shared
the actual raw API response: the code assumed the response's `ref`
field was a nested object with a `jobAd` key inside it. It's actually
a plain string — SmartRecruiters' own API detail-endpoint URL for that
posting, not a link a human would open. Fixed by building the real
public URL directly from the response's `company.identifier` and `id`
fields instead of trusting the `ref` field's assumed shape.

### Qualcomm's Workday URL always failed

The generic Workday pattern (`{tenant}.wd{N}.myworkdayjobs.com/wday/
cxs/...`) returned a 422 for Qualcomm on every attempt. Aman found
Qualcomm's real public career site runs an entirely different, custom
search layer (`careers.qualcomm.com/api/pcsx/search`) with a
completely different response shape — even though Qualcomm's
underlying ATS may still be Workday. Rather than force this into the
generic Workday parser, built a dedicated one-off function
(`fetch_qualcomm`) from the confirmed real response, and added a new
`CUSTOM_COMPANIES` category to the codebase for exactly this situation
— a reminder that "same ATS platform" doesn't always mean "same public
API," since some companies put a different search layer in front of
their real ATS.

### The "stuck at exactly 40 jobs" mystery

Sixteen to seventeen Workday companies consistently returned exactly
40 jobs, regardless of their real size — a company with 2,000 real
openings and a company with 91 both stopped at the same number. Took
three rounds to find the real cause:

1. **First guess: Workday caps the reported `total` for anonymous
   requests.** Disproven by fetching Visa's raw page-1 response
   directly — `total: 742`, a genuine number, not a suspiciously round
   cap.
2. **Second guess: rate limiting from firing paginated requests with
   no delay between them.** Added a 1.5-second delay between pages as
   a direct test. Disproven — identical result with the delay in
   place; KLA's `total` field still dropped to 0 on page 2.
3. **Real cause, confirmed:** Workday's `total` field becomes
   unreliable starting from page 2 — it silently reports 0 even though
   that same page still contains real, valid postings. The original
   pagination loop trusted `total` to decide when to stop
   (`offset >= total: break`), so the instant `total` lied, a real
   page of jobs got discarded as "we must be done" — explaining
   exactly why the cap always landed at 40 (page 1 + one more real
   page, then a premature stop).

Fix: stop trusting `total` for anything. Use whether the page itself
came back full-size or short (`len(postings) < page_size`) as the
actual stopping signal — a fact directly observed from the response,
not a field that had already been caught lying. Verified by
reproducing the exact failure pattern in a synthetic test first
(confirmed the fix recovers the full count), then confirmed for real
against KLA (49/49 recovered) and APTIV (731/731 recovered across 37
real paginated requests, zero failures).

The delay from step 2, once proven unnecessary, was removed —
diagnostic logging added specifically to distinguish between the
competing hypotheses was also removed once its job was done, since a
print statement that no longer changes any decision is just noise.

### Sprinto slug regression

Lever's slug for Sprinto is case-sensitive (`Sprinto`, not
`sprinto`) — fixed once, then silently reverted to lowercase during an
unrelated rewrite of `companies.py`, and had to be caught and fixed
again. Small, but a reminder that a fix made once needs to survive
later edits, not just work in the moment.

### RippleHire — real payload, still doesn't work outside a browser

Aman captured the EXACT real POST payload his own browser sends for
both Axis Bank and Tredence (both run RippleHire) straight from
DevTools - not a guess. Tried it verbatim, plus every reasonable header
combination (session cookies from the page's own prior GET calls,
Referer, Origin, User-Agent spoofing, Sec-Fetch-* headers): every
single attempt got back the same generic `An unexpected error
occurred`, a genuine HTTP 500 (not a 403/bot-block page, which pointed
toward a real backend exception from something still missing, not a
WAF). Left as an open `NEEDS_MORE_INFO` item rather than shipped as
broken-looking code - the payload alone isn't sufficient; something
about a live browser session (a header, a cookie, or genuinely
TLS/JA3-level bot fingerprinting the requests library can't replicate)
is still missing, and guessing further wasn't going to find it.

### SquarePoint's job links point at their own custom career site, not
### a URL Greenhouse's API can build correctly

Greenhouse's own API for SquarePoint's board returns a real
`absolute_url` for every job - but it points at
`squarepoint-capital.com/open-opportunities?id={greenhouse_id}&gh_jid=
{greenhouse_id}`, which SquarePoint's own custom frontend doesn't
actually resolve to a specific job at all (it silently falls back to
the generic listing page). Confirmed live: SquarePoint's real "Apply"
links use a COMPLETELY different internal ID space
(`opportunity-details?id={their_own_id}`) with zero overlap with
Greenhouse's IDs for the same postings, and there's no plain,
HTTP-fetchable API to resolve one to the other - the mapping only
exists inside their client-side JavaScript (confirmed by checking:
their `/open-opportunities` page returns almost no data server-side,
everything loads via client-rendered JS with no discoverable backing
API call). Running a full browser per fetch just to resolve one URL
isn't practical for a backend pipeline that needs to stay fast, so
SquarePoint's links now point at the real listing page - honest about
not being able to deep-link, rather than confidently wrong.

### A leftover test server quietly broke Aman's own local server

After building the FastAPI backend, several rounds of live-testing it
(starting/stopping `uvicorn` from within a Claude session, to verify
each fix) left ONE test process running on port 8000 that never got
cleaned up. When Aman later started his OWN real server on the same
port, Windows allowed BOTH processes to bind - and the stale one was
silently intercepting some traffic, matching exactly what Aman saw
("reloaded the page, nothing happened in the terminal"). Found by
checking `netstat` for the port and cross-referencing PIDs against
`Get-Process` - the leftover process was still running from a test
started nearly two days earlier. Killed it; confirmed via `curl` that
only the real server remained afterward.

Separately (found while investigating the SAME "nothing in the
terminal" report, after the stale-process fix): `http://localhost:8000`
and `http://127.0.0.1:8000` are NOT guaranteed to reach the same
place - `uvicorn` without an explicit `--host` binds ONLY the IPv4
loopback (`127.0.0.1`), and a browser trying `localhost` can attempt
the IPv6 loopback (`::1`) first depending on OS/browser behavior;
confirmed live that this server genuinely refuses connections on `::1`
entirely. Switching the browser URL to `127.0.0.1` directly was tried
next but Aman reported the SAME symptom even then - ruled out as the
real cause once the actual root cause below was found; ultimately
resolved when Aman restarted his laptop entirely, which cleared
whatever OS-level socket state was involved.

**Root cause, found later, on a DIFFERENT occasion:** an ORPHANED
socket, not a live process. A process killed with `Stop-Process -Force`
(confirmed gone via `Get-Process` - no PID, no process) can still leave
its socket showing as `LISTENING` in `netstat` and silently
accepting+hanging connections for the full request timeout - Windows
doesn't always release a socket the instant its owning process dies. A
second, related variant of the exact same symptom turned up again
during frontend testing (2026-08-29): after stopping a test `uvicorn`
process, `netstat` still showed port 8000 as `LISTENING` even though
`Get-Process` confirmed that PID was gone - the actual culprit,
found via `Get-CimInstance Win32_Process`, was a leftover
`multiprocessing` spawn WORKER (`--multiprocessing-fork`) whose parent
process had already died, but which was still alive and still holding
the socket open on its own. Killing that worker process directly (not
its already-dead parent) is what actually freed the port. General
lesson for this project going forward: `netstat` showing `LISTENING`
is not proof a real, functioning server is behind it - cross-reference
the PID against `Get-Process`/`Get-CimInstance` before trusting it,
and remember a killed process can still have orphaned children holding
the resource it used to own.

### Workday platform outage — confirmed external, not a code bug

Aman reported "many Workday companies failing" on a run. Rather than
assume a regression in `fetch_workday` (which had already been
live-verified working, see the "stuck at exactly 40 jobs" story
above), checked directly against multiple Workday tenants and
confirmed the failures were coming from Workday's OWN platform being
down at the time - not this codebase. Documented here mainly as a
reminder of the general practice: a sudden multi-company failure
pattern is a strong signal to check whether the shared underlying
platform itself is having a bad day, before assuming a fetcher broke.

---

## Engineering practices that emerged from this

Worth naming explicitly since they've held up across every real bug
so far:

- **Never guess when a cheap, concrete test can decide it instead.**
  Every wrong hypothesis in this project (case sensitivity, capped
  totals, rate limiting) got resolved by fetching one real response
  and looking at it directly — not by reasoning harder about which
  guess was more plausible.
- **When a guess is wrong, say so plainly and move to the next test.**
  Three wrong turns on the same bug is a normal part of debugging
  something with no documentation, not a sign to keep defending a
  theory.
- **Normalize at the boundary.** Every platform's fetcher converts to
  one common shape immediately — nothing downstream (scoring, state,
  matching) ever needs to know which platform a job came from.
- **Test small before trusting a change on the full run.** A fix got
  verified against one small company (3 pages) before being trusted
  against a 37-page company, before being trusted against the full
  20-company Tier 2 run.
- **Remove instrumentation once it's done its job.** Diagnostic
  logging and a test delay both got added specifically to distinguish
  between hypotheses, and both got removed once the real answer was
  confirmed — logging that no longer changes a decision is clutter,
  not safety.

---

## Next steps / open items

1. **A real replacement for `GET /jobs/new`.** Deliberately removed
   from the backend (see the `/refresh` architecture section above) on
   Aman's own instruction that he'll build a workaround for this
   "without creating a new endpoint" later - not yet designed. Likely
   candidates once it's picked back up: diffing consecutive `/refresh`
   results client-side, or persisting a seen-set in the browser
   (`localStorage`) rather than the backend's old `seen_jobs.json`
   approach. `find_new_matches()`/`state.py` were left untouched in the
   backend specifically so they're available to reuse if that ends up
   being the right shape after all.
2. **Missing-required-skill penalty in scoring.py.** The Schrödinger
   finding above (85 score built almost entirely from Nice-to-Have
   matches while the #1 Required skill has zero overlap) is real and
   unaddressed - needs a deliberate design conversation, not a rushed
   fix.
3. **The LLM-based domain-fit stage**, deliberately deferred every time
   it's come up so far - scoring.py is still pattern-matching, not
   semantic understanding (can't tell "kernel debugging" and "business
   workflow automation" apart even when both technically mention C++).
   Discussed as a two-stage design (cheap keyword pre-filter, then an
   LLM call only on jobs that already clear a lower bar) but blocked on
   Aman setting up an Anthropic API key - guidance given, not yet done
   as of this log entry.
4. **Workday/SmartRecruiters description enrichment** is built and
   live-verified, but only enriches jobs whose TITLE already looks
   relevant - by design (avoids paying for a detail request on
   postings that were always going to get filtered out), but worth
   remembering if a real title ever slips past `is_relevant_title()`'s
   keyword list.
5. **Notification channel.** The frontend now makes results viewable
   without curl/Postman, but there's still no PUSH notification
   (email, Telegram, etc.) - would need something to call `POST
   /refresh` on a schedule and forward whatever's new, once the
   "what's new" question from item 1 above has an answer.
6. **Scheduling.** Nothing calls `POST /refresh` on a recurring
   schedule yet - a person (or something else) still has to trigger it
   manually, whether via the frontend button or a direct API call.
7. **The remaining `NEEDS_MORE_INFO` companies** — RippleHire (Axis
   Bank/Tredence - real payload still doesn't work outside a browser,
   see Challenges), TurboHire (Pine Labs/Flipkart - 0 current openings
   at Pine Labs, Flipkart's token expires hourly with no found minting
   endpoint), and the shared Cornerstone OnDemand platform (Siemens/
   Deloitte/CornerStone - needs a bearer token only visible in an
   authenticated session). Each needs one more piece of evidence
   (typically a full DevTools "Copy as cURL") that wasn't obtainable
   without Aman's own browser session.
8. **A decision on Tier 3** — worth deliberately deciding whether
   covering iCIMS/SuccessFactors (the two platforms confirmed
   technically possible) is worth the extra engineering effort, given
   they'd need meaningfully different, more fragile approaches than
   everything built so far.
9. **Frontend polish and deployment.** The frontend is functionally
   complete and live-verified against a local backend, but has had no
   real design pass beyond the base dark/light theme inherited from
   the Vite scaffold, and neither the frontend nor backend has been
   deployed anywhere outside `localhost` yet - both still assume a
   same-machine dev setup (hardcoded default `VITE_API_BASE_URL`, CORS
   allowlist scoped to `localhost:5173` only).
