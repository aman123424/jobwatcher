import { useNavigate } from "react-router-dom";
import { JobList } from "../components/JobList";
import { JobsTabs } from "../components/JobsTabs";
import { useAuth } from "../hooks/useAuth";
import { useJobs } from "../hooks/useJobs";

/**
 * The home page AND the jobs list, combined into one screen (merged
 * 2026-09-02 - previously a separate Home page led here via a
 * "Get Started" button; Aman asked for that extra click-through step
 * removed, so this now IS what a logged-in user lands on directly).
 */
export function JobsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { tab, setTab, jobs, isLoading, isRefreshing, error, updateStatus, refresh } = useJobs();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="jobs-page">
      <header className="jobs-page-header">
        <h1>JobWatcher</h1>
        <span className="jobs-page-user">{user?.name}</span>
        <button type="button" className="logout-button" onClick={handleLogout}>
          Log out
        </button>
      </header>

      <button type="button" className="refresh-button" onClick={refresh} disabled={isRefreshing}>
        {isRefreshing ? "Refreshing…" : "Refresh Jobs"}
      </button>

      <JobsTabs tab={tab} onChange={setTab} />

      <main>
        <JobList jobs={jobs} isLoading={isLoading} error={error} onSetStatus={updateStatus} />
      </main>
    </div>
  );
}
