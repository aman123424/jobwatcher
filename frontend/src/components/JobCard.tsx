import type { JobOut, JobStatus } from "../api/types";

interface JobCardProps {
  job: JobOut;
  onSetStatus: (jobId: string, status: JobStatus) => void;
}

const STATUS_BUTTONS: { value: JobStatus; label: string }[] = [
  { value: "saved", label: "Save" },
  { value: "applied", label: "Applied" },
  { value: "not_interested", label: "Not interested" },
];

/**
 * One job, purely presentational - all it knows how to do is display
 * a JobOut and report which status button was clicked; useJobs.ts
 * owns what actually happens next (the real API call + refetch).
 *
 * Every status button always shows, on every tab, with whichever one
 * matches the job's CURRENT status highlighted - rather than showing
 * different buttons per tab (e.g. hiding "Save" while already on the
 * Saved tab) - simpler and more predictable: the same three actions,
 * in the same place, everywhere, and clicking the already-active one
 * is a harmless no-op (the backend upsert is idempotent either way).
 */
export function JobCard({ job, onSetStatus }: JobCardProps) {
  return (
    <article className="job-card">
      <header className="job-card-header">
        <div>
          <h3 className="job-title">
            <a href={job.link} target="_blank" rel="noreferrer">
              {job.title}
            </a>
          </h3>
          <p className="job-company">
            {job.company_name}
            {job.location ? ` · ${job.location}` : ""}
          </p>
        </div>
      </header>

      {(job.tech_stack.length > 0 || job.years_experience_required !== null) && (
        <div className="job-meta">
          {job.tech_stack.map((skill) => (
            <span key={skill} className="job-skill-badge">
              {skill}
            </span>
          ))}
          {job.years_experience_required !== null && (
            <span className="job-yoe-badge">{job.years_experience_required}+ yrs</span>
          )}
        </div>
      )}

      <div className="job-card-footer">
        {job.posted_at && <span className="job-posted-date">Posted {job.posted_at}</span>}
        <div className="job-status-buttons">
          {STATUS_BUTTONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              className={`job-status-button${job.status === value ? " active" : ""}`}
              onClick={() => onSetStatus(job.job_id, value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </article>
  );
}
