import type { ChangeEvent } from "react";
import { Link } from "react-router-dom";
import "./JobCard.scss";
import type { JobOut, JobStatus } from "../api/types";
import { useAuth } from "../hooks/useAuth";

interface JobCardProps {
  job: JobOut;
  /**
   * Which tab-specific Rejected action to show next to the dropdown,
   * if any - `undefined` on every tab except My Jobs ("reject", since
   * every job there is guaranteed Applied) and Rejected ("unreject",
   * since every job there is guaranteed Rejected). This is TAB-driven,
   * computed once by JobsPage.tsx and threaded through JobList, not
   * derived per-card from job.status - a card never needs to guess
   * which tab it's rendering in.
   */
  rejectAction?: "reject" | "unreject";
  onSetStatus: (jobId: string, status: JobStatus | null) => void;
}

const STATUS_OPTIONS: { value: JobStatus; label: string }[] = [
  { value: "saved", label: "Save" },
  { value: "applied", label: "Applied" },
  { value: "not_interested", label: "Not interested" },
];

/**
 * One job, purely presentational - all it knows how to do is display
 * a JobOut and report a status change; useJobs.ts owns what actually
 * happens next (the real API call, in the background).
 *
 * REWORKED 2026-09-03 (Aman's own call): the three core statuses
 * (Save/Applied/Not interested) used to be three separate buttons,
 * plus a conditionally-shown fourth "Rejected" button - four buttons
 * on every card looked cluttered. Now it's ONE <select> dropdown for
 * the three core statuses (picking "No status" clears it, replacing
 * the old "click the active button again to toggle off" gesture,
 * which doesn't translate to a native dropdown), plus AT MOST one
 * extra Rejected/Mark as Applied button, shown only on the two tabs
 * where it's actually relevant (see `rejectAction` above) rather than
 * on every card everywhere.
 */
export function JobCard({ job, rejectAction, onSetStatus }: JobCardProps) {
  const { user } = useAuth();

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    const value = event.target.value;
    onSetStatus(job.job_id, value === "" ? null : (value as JobStatus));
  }

  // The <select>'s own value has to be one of its actual <option>
  // values (or "") - job.status can be "rejected" too, which isn't
  // one of the three core options, so that case falls back to "" (no
  // core status selected) rather than being an invalid/silently
  // ignored value.
  const selectValue = job.status && job.status !== "rejected" ? job.status : "";

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
        {/* Admin-only resume-fit score (2026-09-04) - the backend
            never sends a score at all to a non-admin (see api.py's
            JobOut.score docstring), so `user?.is_admin` is really just
            avoiding a dead link for everyone else, not the real gate.
            Unscored (job.score === null) still shows as a clickable
            "Score" placeholder - clicking it is what triggers the
            lazy score_job() computation on JobScorePage. */}
        {user?.is_admin && (
          <Link
            to={`/jobs/${job.job_id}/score`}
            className={`job-score-badge${job.score === null ? " job-score-badge-unscored" : ""}`}
          >
            {job.score === null ? "Score" : `${job.score}%`}
          </Link>
        )}
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
        <div className="job-status-controls">
          <select className="job-status-select" value={selectValue} onChange={handleStatusChange}>
            <option value="">No status</option>
            {STATUS_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          {rejectAction === "reject" && (
            <button type="button" className="job-status-button" onClick={() => onSetStatus(job.job_id, "rejected")}>
              Rejected
            </button>
          )}
          {rejectAction === "unreject" && (
            // "Rejected is a substate of Applied" (Aman's own framing,
            // 2026-09-03) - undoing one doesn't clear the job back to
            // no status, it specifically restores Applied.
            <button
              type="button"
              className="job-status-button active"
              onClick={() => onSetStatus(job.job_id, "applied")}
            >
              Rejected
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
