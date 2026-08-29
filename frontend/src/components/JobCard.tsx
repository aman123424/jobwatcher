import type { JobMatch } from "../api/types";

interface JobCardProps {
  job: JobMatch;
}

/** Renders one job. Purely presentational - all it knows how to do is display a JobMatch it's handed. */
export function JobCard({ job }: JobCardProps) {
  return (
    <article className={`job-card${job.is_strong_match ? " strong-match" : ""}`}>
      <header className="job-card-header">
        <div>
          <h3 className="job-title">
            <a href={job.job_link} target="_blank" rel="noreferrer">
              {job.job_title}
            </a>
          </h3>
          <p className="job-company">{job.company_name}</p>
        </div>
        <span className="job-score" title="Match score out of 100">
          {job.match_score}
        </span>
      </header>

      <p className="job-reason">{job.match_reason}</p>

      {job.job_posted_date && <p className="job-posted-date">Posted {job.job_posted_date}</p>}
    </article>
  );
}
