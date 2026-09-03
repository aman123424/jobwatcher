import { AvatarMenu } from "../components/AvatarMenu";
import { JobList } from "../components/JobList";
import { JobsTabs } from "../components/JobsTabs";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../hooks/useAuth";
import { useJobs } from "../hooks/useJobs";

/**
 * The home page AND the jobs list, combined into one screen (merged
 * 2026-09-02 - previously a separate Home page led here via a
 * "Get Started" button; Aman asked for that extra click-through step
 * removed, so this now IS what a logged-in user lands on directly).
 */
export function JobsPage() {
  const { user } = useAuth();
  const { tab, setTab, jobs, isLoading, isRefreshing, error, statusError, updateStatus, refresh, lastRefreshedAt } =
    useJobs();

  // My Jobs guarantees every job shown is Applied - "Rejected" there
  // means "mark it". Rejected guarantees every job shown IS rejected -
  // "Rejected" there means "undo, back to Applied" (see JobCard.tsx).
  // Every other tab shows neither - Rejected only makes sense relative
  // to one of those two states.
  const rejectAction = tab === "mine" ? "reject" : tab === "rejected" ? "unreject" : undefined;

  return (
    <div className="jobs-page">
      <header className="jobs-page-header">
        <h1>JobWatcher</h1>
        <div className="jobs-page-header-right">
          <ThemeToggle />
          {user && <AvatarMenu name={user.name} />}
        </div>
      </header>

      <div className="refresh-row">
        <button type="button" className="refresh-button" onClick={refresh} disabled={isRefreshing}>
          {isRefreshing ? "Refreshing…" : "Refresh Jobs"}
        </button>
        {lastRefreshedAt && <span className="last-refreshed">Last fetched {lastRefreshedAt}</span>}
      </div>

      <JobsTabs tab={tab} onChange={setTab} />

      {/* A single job's status update failing in the background - the
          list itself still loaded fine, so this stays a small banner
          ABOVE the list rather than replacing it (see JobList's own
          `error` prop below, which is for the list failing to load at
          all - a genuinely different, more serious case). */}
      {statusError && <p className="status-error-banner">{statusError}</p>}

      <main>
        <JobList
          jobs={jobs}
          isLoading={isLoading}
          error={error}
          rejectAction={rejectAction}
          onSetStatus={updateStatus}
        />
      </main>
    </div>
  );
}
