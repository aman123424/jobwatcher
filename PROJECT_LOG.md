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

Six files now (was five before the FastAPI backend), each with one job:

| File | Responsibility |
|---|---|
| `companies.py` | Pure data — which companies, which platform, which slug/identifier. Split into `TIER1_COMPANIES`, `TIER2_COMPANIES`, `CUSTOM_COMPANIES` (one-off non-standard integrations), and `NEEDS_MORE_INFO` (flagged, not yet trustworthy enough to include). |
| `fetchers.py` | One function per platform. Each one calls that platform's API and normalizes the very different response shapes into one common job dict — `source_company`, `platform`, `job_id`, `title`, `location`, `url`, `updated_at`, `raw_description`. Everything downstream only ever sees this one shape, regardless of which platform a job came from. Also owns per-company fetching concurrency (`ThreadPoolExecutor`, 10 at once) and, for platforms confirmed sorted newest-first (Workday, SmartRecruiters), early-stop-on-staleness logic. |
| `scoring.py` | Evidence-weighted, JD-importance-aware match scoring against Aman's real resume content (rewritten 2026-08-28 - see that section above), 0-100, plus a plain-English reason. Also filters to Software-Engineer-shaped titles, India-only locations, and infers rough seniority from the title. |
| `state.py` | Remembers which jobs have already been shown, across runs, via a JSON file keyed on `(platform, job_id)` — so a re-run only reports genuinely new postings, not the same list every time. |
| `main.py` | Runs the whole pipeline end to end. Exposes two entry points: `fetch_and_score_all()` (read-only: fetch → filter → score, no side effects) and `find_new_matches()` (built on top of the first: also filters by `MIN_SCORE`, diffs against `state.py`, logs, and saves) — both the CLI's `run()` and `api.py`'s endpoints call these same two functions rather than each having their own copy of the pipeline logic. |
| `api.py` | FastAPI backend (added 2026-08-27) — three GET endpoints (`/jobs`, `/jobs/best_match`, `/jobs/new`) exposing the exact same pipeline over HTTP. No auth (deliberate, for local/personal use). See the FastAPI section below for the full design. |

The normalization step in `fetchers.py` is the load-bearing design
choice — it's what let three completely different pagination/response
formats (Greenhouse's `jobs` array, SmartRecruiters' paginated
`content` list, Workday's POST-based search) plug into the exact same
scoring and state-tracking logic without either of those ever needing
to know which platform a job came from.

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

As of the most recent full run: **43 companies configured** (19 Tier 1
+ 20 Tier 2 + 4 custom). `companies.py` is the current source of truth
for the exact list — this number will keep moving as more companies
get resolved out of `NEEDS_MORE_INFO`.

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

---

## The FastAPI backend (2026-08-27)

Converted the CLI-only tool into a live HTTP API, reusing 100% of the
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
next but Aman reported the SAME symptom even then - still unresolved
as of this log entry; the leading theory being investigated next is
that `/jobs/best_match` triggers the full ~1-4 minute live pipeline and
`uvicorn`'s access-log line only prints AFTER a request finishes, not
when it arrives - so "nothing in the terminal" a few seconds after
reloading may just mean the request is still in flight, not that it
never arrived. Not yet confirmed either way.

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

1. **Unresolved right now: `/jobs/best_match` "nothing in the
   terminal."** See the last Challenges entry above - stale-process
   conflict fixed, IPv6/localhost theory tested and ruled out (Aman
   tried `127.0.0.1` directly, same symptom), leading theory is the
   request is just still running (full pipeline takes 1-4 minutes,
   access-log line only prints on completion) but this has NOT been
   confirmed yet - was mid-investigation when this log entry was
   written, including a background `curl` test to the same endpoint
   whose result wasn't back yet.
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
5. **Notification channel.** Results are queryable live via the API
   now (`GET /jobs/new` etc.), and still logged to `matches_log.csv`,
   but no PUSH notification (email, Telegram, etc.) exists yet - the
   API makes this a much smaller next step than it used to be (just
   needs something to poll `/jobs/new` on a schedule and forward what
   comes back).
6. **Scheduling.** Nothing runs the API or the CLI on a recurring
   schedule yet - would need a cron job, a scheduled cloud function, or
   similar to poll `/jobs/new` automatically instead of Aman (or
   something) calling it manually.
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
