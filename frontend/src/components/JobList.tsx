import type { JobMatch } from "../api/types";
import { JobCard } from "./JobCard";

interface JobListProps {
  jobs: JobMatch[];
  isLoading: boolean;
  error: string | null;
  hasEverRefreshed: boolean;
}

/**
 * Handles every state the job list can be in - loading, error, no
 * data yet, empty result, and a real list - so JobCard itself only
 * ever has to handle the "happy path" of rendering one real job (see
 * JobCard.tsx). App.tsx doesn't need to know about any of these cases
 * either; it just renders <JobList /> and hands it what useJobsData
 * already tracked.
 */
export function JobList({ jobs, isLoading, error, hasEverRefreshed }: JobListProps) {
  if (error) {
    return <p className="job-list-status job-list-error">{error}</p>;
  }

  if (isLoading) {
    return <p className="job-list-status">Loading…</p>;
  }

  if (!hasEverRefreshed) {
    return (
      <p className="job-list-status">
        No data yet — click "Fetch Fresh" above to pull today's postings.
      </p>
    );
  }

  if (jobs.length === 0) {
    return <p className="job-list-status">No matching jobs in the last refresh.</p>;
  }

  return (
    <div className="job-list">
      {jobs.map((job) => (
        // platform isn't in JobMatch, but job_id is only unique WITHIN
        // one company's job board (see state.py's own _job_key() in the
        // backend for the same reasoning) - company_name + job_id
        // together is what's actually unique across the whole list.
        <JobCard key={`${job.company_name}-${job.job_id}`} job={job} />
      ))}
    </div>
  );
}
