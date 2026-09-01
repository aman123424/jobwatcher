import { useNavigate } from "react-router-dom";
import { JobList } from "../components/JobList";
import { JobsTabs } from "../components/JobsTabs";
import { useAuth } from "../hooks/useAuth";
import { useJobs } from "../hooks/useJobs";

export function JobsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { tab, setTab, jobs, isLoading, error, updateStatus } = useJobs();

  return (
    <div className="jobs-page">
      <header className="jobs-page-header">
        <button type="button" className="back-button" onClick={() => navigate("/")}>
          ← Home
        </button>
        <h1>JobWatcher</h1>
        <span className="jobs-page-user">{user?.name}</span>
      </header>

      <JobsTabs tab={tab} onChange={setTab} />

      <main>
        <JobList jobs={jobs} isLoading={isLoading} error={error} onSetStatus={updateStatus} />
      </main>
    </div>
  );
}
