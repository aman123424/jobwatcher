import type { JobOut, JobStatus } from "../api/types";
import { JobCard } from "./JobCard";

interface JobListProps {
  jobs: JobOut[];
  isLoading: boolean;
  error: string | null;
  /** Forwarded to every JobCard unchanged - see JobCard.tsx's own docstring for what it controls. Computed once by JobsPage.tsx from the active tab, not per-job. */
  rejectAction?: "reject" | "unreject";
  onSetStatus: (jobId: string, status: JobStatus | null) => void;
}

/** Handles every state the list can be in (loading, error, empty, real results) so JobCard only ever has to render one real job. */
export function JobList({ jobs, isLoading, error, rejectAction, onSetStatus }: JobListProps) {
  if (error) {
    return <p className="job-list-status job-list-error">{error}</p>;
  }

  if (isLoading) {
    return <p className="job-list-status">Loading…</p>;
  }

  if (jobs.length === 0) {
    return <p className="job-list-status">No jobs here yet.</p>;
  }

  return (
    <div className="job-list">
      {jobs.map((job) => (
        <JobCard key={job.job_id} job={job} rejectAction={rejectAction} onSetStatus={onSetStatus} />
      ))}
    </div>
  );
}
