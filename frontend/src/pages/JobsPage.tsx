import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { JobList } from "../components/JobList";
import { JobsTabs } from "../components/JobsTabs";
import "./JobsPage.scss";
import { useJobs } from "../hooks/useJobs";

// Same round-trip problem as the active tab (see useJobs.ts's own
// comment on TAB_STORAGE_KEY): navigating to a job's score page and
// back fully unmounts/remounts JobsPage, so plain useState/scroll
// position would reset. sessionStorage carries both across that gap.
const SEARCH_STORAGE_KEY = "jobwatcher:companySearch";
const SCROLL_STORAGE_KEY = "jobwatcher:jobsScrollY";

/**
 * The home page AND the jobs list, combined into one screen (merged
 * 2026-09-02 - previously a separate Home page led here via a
 * "Get Started" button; Aman asked for that extra click-through step
 * removed, so this now IS what a logged-in user lands on directly).
 */
export function JobsPage() {
  const {
    tab,
    setTab,
    jobs,
    isLoading,
    isRefreshing,
    error,
    statusError,
    updateStatus,
    refresh,
    lastRefreshedAt,
    failedCompanies,
  } = useJobs();
  // Collapsed by default - the count alone is the point (a quiet,
  // always-visible signal that something didn't fetch cleanly,
  // instead of that silently disappearing into the backend's own
  // logs) - the actual company names are one click away, not shoved
  // in front of every refresh whether or not anyone wants to read them.
  //
  // POPOVER, NOT AN INLINE LIST (reworked 2026-09-12, after Aman's own
  // feedback that the first version - a <ul> in normal document flow -
  // shoved the search bar and every job card down the instant it
  // opened, reading as if the whole page had navigated somewhere else.
  // Same "position: absolute, closes on an outside click" pattern
  // AvatarMenu.tsx already uses for its dropdown - see that component
  // for the precedent this mirrors) - the popover floats OVER the page
  // instead of pushing it, so opening/closing it never moves anything
  // else on screen.
  const [showFailedCompanies, setShowFailedCompanies] = useState(false);
  const failedCompaniesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showFailedCompanies) return;
    function handleClickOutside(event: MouseEvent) {
      if (failedCompaniesRef.current && !failedCompaniesRef.current.contains(event.target as Node)) {
        setShowFailedCompanies(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showFailedCompanies]);
  // Company-name search (Aman's own sketch, 2026-09-03) - filters
  // whatever the active tab already loaded, client-side. Deliberately
  // NOT sent to the backend as a query param: the jobs for a tab are
  // already fully fetched, and typing a search shouldn't re-hit the
  // network on every keystroke for a filter this cheap to do locally.
  const [companySearch, setCompanySearchState] = useState(() => sessionStorage.getItem(SEARCH_STORAGE_KEY) ?? "");
  const setCompanySearch = (value: string) => {
    sessionStorage.setItem(SEARCH_STORAGE_KEY, value);
    setCompanySearchState(value);
  };

  // Restore scroll position once the tab's jobs have actually rendered
  // (restoring any earlier, while the list is still empty/loading,
  // would have nothing tall enough to scroll to yet). Runs once per
  // mount - scrollRestored guards against re-firing on every future
  // isLoading flip (switching tabs, refreshing).
  const scrollRestored = useRef(false);
  useEffect(() => {
    if (isLoading || scrollRestored.current) return;
    scrollRestored.current = true;
    const savedY = sessionStorage.getItem(SCROLL_STORAGE_KEY);
    if (savedY) window.scrollTo(0, Number(savedY));
  }, [isLoading]);

  // Captured on unmount, i.e. exactly when navigating away to the
  // score page - not on every scroll event, which would just be wasted
  // writes for the common case of never leaving this page at all.
  //
  // useLayoutEffect, NOT useEffect: a plain useEffect's cleanup runs
  // asynchronously, after React has already committed the DOM swap to
  // the new route's (much shorter) content - by then the browser has
  // already clamped window.scrollY back down to fit, so the "captured"
  // value was always 0, silently. useLayoutEffect's cleanup runs
  // synchronously as part of that same commit, while this page's own
  // (still-tall) content is still in the document, so it reads the
  // real position.
  useLayoutEffect(() => {
    return () => {
      sessionStorage.setItem(SCROLL_STORAGE_KEY, String(window.scrollY));
    };
  }, []);
  const filteredJobs = companySearch.trim()
    ? jobs.filter((j) => j.company_name.toLowerCase().includes(companySearch.trim().toLowerCase()))
    : jobs;

  // My Jobs guarantees every job shown is Applied - "Rejected" there
  // means "mark it". Rejected guarantees every job shown IS rejected -
  // "Rejected" there means "undo, back to Applied" (see JobCard.tsx).
  // Every other tab shows neither - Rejected only makes sense relative
  // to one of those two states.
  const rejectAction = tab === "mine" ? "reject" : tab === "rejected" ? "unreject" : undefined;

  return (
    <div className="jobs-page">
      <AppHeader />

      <div className="refresh-row">
        <button
          type="button"
          className="refresh-button"
          onClick={() => {
            setShowFailedCompanies(false);
            void refresh();
          }}
          disabled={isRefreshing}
        >
          {isRefreshing ? "Refreshing…" : "Refresh Jobs"}
        </button>
        {lastRefreshedAt && <span className="last-refreshed">Last fetched {lastRefreshedAt}</span>}
      </div>

      {/* A quiet, always-visible failure signal (Aman's own explicit
          ask, 2026-09-12) - previously a company whose fetch genuinely
          broke (a real network/API error, not just "zero open roles
          right now") was indistinguishable from one with nothing new,
          visible only in backend logs nobody was watching. Collapsed
          to just the count by default; the company names themselves
          are one click away, not forced in front of every refresh. */}
      {failedCompanies.length > 0 && (
        <div className="failed-companies-row" ref={failedCompaniesRef}>
          <button
            type="button"
            className="failed-companies-toggle"
            onClick={() => setShowFailedCompanies((prev) => !prev)}
            aria-haspopup="true"
            aria-expanded={showFailedCompanies}
          >
            {failedCompanies.length} {failedCompanies.length === 1 ? "company" : "companies"} failed to fetch
          </button>
          {showFailedCompanies && (
            <div className="failed-companies-popover" role="alert">
              <p className="failed-companies-popover-title">
                Couldn't fetch the latest jobs for {failedCompanies.length === 1 ? "this company" : "these companies"}:
              </p>
              <ul className="failed-companies-list">
                {failedCompanies.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="jobs-filter-row">
        <input
          type="text"
          className="company-search-input"
          placeholder="Search companies"
          value={companySearch}
          onChange={(e) => setCompanySearch(e.target.value)}
          aria-label="Search companies"
        />
        <JobsTabs tab={tab} onChange={setTab} />
      </div>

      {/* A single job's status update failing in the background - the
          list itself still loaded fine, so this stays a small banner
          ABOVE the list rather than replacing it (see JobList's own
          `error` prop below, which is for the list failing to load at
          all - a genuinely different, more serious case). */}
      {statusError && <p className="status-error-banner">{statusError}</p>}

      <main>
        <JobList
          jobs={filteredJobs}
          isLoading={isLoading}
          error={error}
          rejectAction={rejectAction}
          emptyMessage={companySearch.trim() ? `No companies match "${companySearch.trim()}".` : undefined}
          onSetStatus={updateStatus}
        />
      </main>
    </div>
  );
}
