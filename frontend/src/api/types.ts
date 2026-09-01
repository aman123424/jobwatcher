/**
 * Mirrors backend/auth_routes.py's Pydantic models field-for-field -
 * the same "one file, kept in sync with the backend's actual shapes"
 * approach the old job-related types.ts used, just for auth now.
 */

export interface AuthUser {
  user_id: string;
  name: string;
  email: string;
  tier: "free" | "paid";
}

/** What POST /auth/register and POST /auth/login both return. */
export interface AuthResponse extends AuthUser {
  access_token: string;
  token_type: string;
}

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

/** The three states a user can put a job into - mirrors backend/models.py's JobStatus enum exactly. */
export type JobStatus = "saved" | "applied" | "not_interested";

/**
 * Mirrors backend/api.py's JobOut Pydantic model field-for-field.
 *
 * tech_stack and years_experience_required are real fields already,
 * even though the backend always sends [] / null right now - the
 * resume-independent extraction that would populate them isn't built
 * yet (see api.py's own module docstring). Rendered as empty/absent
 * in the UI for now, not hidden from the type - so nothing here needs
 * to change again once that extraction exists.
 */
export interface JobOut {
  job_id: string;
  title: string;
  company_name: string;
  location: string | null;
  link: string;
  tech_stack: string[];
  years_experience_required: number | null;
  posted_at: string | null;
  status: JobStatus | null;
}

export interface JobsListResponse {
  jobs: JobOut[];
}
