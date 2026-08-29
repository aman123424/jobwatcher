/**
 * Mirrors the JobMatch/JobsResponse Pydantic models in backend/api.py
 * exactly - field names, types, and nullability all match on purpose.
 * If those models ever change shape, this is the one place on the
 * frontend that needs to change to match (everything else - the hook,
 * every component - imports these types rather than redefining them,
 * so a shape change only has to be made once).
 */

export interface JobMatch {
  company_name: string;
  job_id: string;
  job_title: string;
  job_link: string;
  match_score: number;
  match_reason: string;
  is_strong_match: boolean;
  /** null when the source platform gives no posted-date info at all (DE Shaw). */
  job_posted_date: string | null;
}

export interface JobsResponse {
  /** ISO 8601 UTC timestamp string, or null if POST /refresh has never been called yet. */
  updated_at: string | null;
  jobs: JobMatch[];
}
