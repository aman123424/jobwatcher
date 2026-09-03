import { useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { JobList } from "../components/JobList";
import { JobsTabs } from "../components/JobsTabs";
import { useJobs } from "../hooks/useJobs";

/**
 * The home page AND the jobs list, combined into one screen (merged
 * 2026-09-02 - previously a separate Home page led here via a
 * "Get Started" button; Aman asked for that extra click-through step
 * removed, so this now IS what a logged-in user lands on directly).
 */
export function JobsPage() {
  const { tab, setTab, jobs, isLoading, isRefreshing, error, statusError, updateStatus, refresh, lastRefreshedAt } =
    useJobs();
  // Company-name search (Aman's own sketch, 2026-09-03) - filters
  // whatever the active tab already loaded, client-side. Deliberately
  // NOT sent to the backend as a query param: the jobs for a tab are
  // already fully fetched, and typing a search shouldn't re-hit the
  // network on every keystroke for a filter this cheap to do locally.
  const [companySearch, setCompanySearch] = useState("");
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
        <button type="button" className="refresh-button" onClick={refresh} disabled={isRefreshing}>
          {isRefreshing ? "Refreshing…" : "Refresh Jobs"}
        </button>
        {lastRefreshedAt && <span className="last-refreshed">Last fetched {lastRefreshedAt}</span>}
      </div>

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
