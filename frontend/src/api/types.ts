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
  /** Gates admin-only UI (currently just the "+ Add Company" button - see AvatarMenu/JobsPage.tsx). The real access check lives server-side (backend/auth.py's get_current_admin) - this only controls whether the button shows at all, never trusted as the actual security boundary. */
  is_admin: boolean;
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

/**
 * The states a user can put a job into - mirrors backend/models.py's
 * JobStatus enum exactly. `rejected` is GATED, not freely settable
 * like the other three - the backend only allows it when a job's
 * CURRENT status is already `applied` (see api.py's set_job_status),
 * and JobCard.tsx only shows the button at all once that's true.
 */
export type JobStatus = "saved" | "applied" | "not_interested" | "rejected";

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
  /** When POST /refresh last actually ran, already formatted (e.g. "2 Sep, 11:47pm") - a shared/global value, the same for every user, not scoped to who triggered it. Null only on a database that's never been refreshed at all. */
  last_refreshed_at: string | null;
}

/** Mirrors backend/api.py's RefreshSummary Pydantic model - what POST /refresh returns (counts, not the jobs themselves). */
export interface RefreshSummary {
  all_jobs_count: number;
  relevant_jobs_count: number;
  inserted: number;
  updated: number;
  skipped_unknown_company: number;
}

/** Mirrors backend/models.py's Platform enum exactly - these values ARE fetchers.py's FETCHERS dict keys, so a value outside this list would never actually be fetchable (see api.py's CreateCompanyRequest, which validates against the same enum server-side). */
export type Platform =
  | "greenhouse"
  | "lever"
  | "ashby"
  | "smartrecruiters"
  | "workday"
  | "pcsx"
  | "amazon"
  | "deshaw"
  | "atlassian";

/** What POST /companies expects - mirrors backend/api.py's CreateCompanyRequest. */
export interface CreateCompanyPayload {
  company_name: string;
  platform: Platform;
  slug: string;
}

/** What POST /companies returns - mirrors backend/api.py's CreateCompanyResponse. */
export interface CreateCompanyResponse {
  id: string;
  name: string;
}
