import type { JobOut, JobStatus } from "../api/types";
import { JobCard } from "./JobCard";

interface JobListProps {
  jobs: JobOut[];
  isLoading: boolean;
  error: string | null;
  onSetStatus: (jobId: string, status: JobStatus) => void;
}

/** Handles every state the list can be in (loading, error, empty, real results) so JobCard only ever has to render one real job. */
export function JobList({ jobs, isLoading, error, onSetStatus }: JobListProps) {
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
        <JobCard key={job.job_id} job={job} onSetStatus={onSetStatus} />
      ))}
    </div>
  );
}
