import type {
  AuthResponse,
  AuthUser,
  CompanyOut,
  CreateCompanyPayload,
  JobScoreOut,
  JobsListResponse,
  JobStatus,
  LoginPayload,
  RefreshSummary,
  RegisterPayload,
  SetJobScorePayload,
} from "./types";

/**
 * Thrown specifically for a 401 response - lets callers (see
 * useJobs.ts) tell "your session expired/is invalid, log in again"
 * apart from every other kind of failure (a genuine network error, a
 * 500, a validation error), which need different handling entirely.
 */
export class UnauthorizedError extends Error {}

/**
 * The backend's own address. Configurable via a .env file (Vite only
 * exposes env vars prefixed VITE_ - see .env.example in this project's
 * root) so this doesn't need a code change to point at a different
 * backend later (a deployed one, a different port, etc). Falls back to
 * the backend's own documented local dev address (see api.py's module
 * docstring: `uvicorn api:app --reload` serves on 127.0.0.1:8000 by
 * default) when no .env is present, so a fresh clone works immediately.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/**
 * Shared request helper - every function below goes through this one
 * place rather than each repeating its own fetch()/error-handling
 * logic (DRY: one definition of "how do we call the backend and what
 * counts as failure", not several near-identical copies that could
 * drift apart).
 *
 * Throws on any non-2xx response or network failure, rather than
 * returning some sentinel value - lets callers use ordinary
 * try/catch instead of checking a boolean/null result after every
 * single call. On a non-2xx response, tries to surface the backend's
 * own `detail` message (FastAPI's standard error shape - e.g.
 * "Invalid email or password") rather than a generic
 * "401 Unauthorized", since that's the actual message a user should
 * see on a failed login/register attempt.
 */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options);
  } catch {
    // A network-level failure (backend not running, CORS blocked,
    // DNS/connection refused) never reaches response.ok below - it
    // throws before that.
    throw new Error(`Could not reach the backend at ${API_BASE_URL}. Is it running?`);
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : undefined;
    } catch {
      // Error body wasn't JSON (or was empty) - fall through to the generic message below.
    }
    const message = detail ?? `${path} failed: ${response.status} ${response.statusText}`;
    if (response.status === 401) {
      throw new UnauthorizedError(message);
    }
    throw new Error(message);
  }

  // A 204 (deleteCompany's response) has no body at all - calling
  // response.json() on it throws (empty string isn't valid JSON), so
  // this has to be checked before parsing, not just handled elsewhere
  // via a caller-side try/catch that would swallow REAL JSON errors too.
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** Builds the Authorization header every job-related endpoint below needs - all of them require a logged-in user (see api.py). */
function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export function register(payload: RegisterPayload): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function login(payload: LoginPayload): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/**
 * GET /auth/me - re-fetches the logged-in user's own info fresh from
 * the database. AuthProvider (see useAuth.tsx) calls this once on app
 * load: login/register only ever set `is_admin` (and everything else)
 * ONCE, at that moment, then cache it in localStorage indefinitely - a
 * flag granted after that stayed invisible to an already-logged-in
 * browser until it happened to log out and back in. This closes that
 * gap without forcing a fresh login.
 */
export function fetchCurrentUser(token: string): Promise<AuthUser> {
  return request<AuthUser>("/auth/me", { headers: authHeaders(token) });
}

/** GET /jobs - "All Jobs": every job posted in the last 24h (or of unknown age), with this user's own status attached where one exists. */
export function fetchAllJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs", { headers: authHeaders(token) });
}

/** GET /jobs/new - "New Jobs": jobs this user has never acted on at all, same 24h freshness window as "All Jobs". */
export function fetchNewJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/new", { headers: authHeaders(token) });
}

/** GET /jobs/mine - "My Jobs": jobs this user marked Applied. No time filter. */
export function fetchMyJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/mine", { headers: authHeaders(token) });
}

/** GET /jobs/saved - "Saved Jobs": jobs this user marked Saved. No time filter. */
export function fetchSavedJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/saved", { headers: authHeaders(token) });
}

/** GET /jobs/rejected - "Rejected": jobs this user marked Rejected. No time filter, same as My Jobs/Saved Jobs. */
export function fetchRejectedJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/rejected", { headers: authHeaders(token) });
}

/** GET /jobs/archived - "Archived Jobs": jobs this user marked Not Interested - UNLIKE Saved/Applied/Rejected, still time-filtered to the same 24h window as "All Jobs" (see api.py). */
export function fetchArchivedJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/archived", { headers: authHeaders(token) });
}

/**
 * POST /refresh - fetches every company live right now and stores the
 * result in the shared database (see api.py/ingest.py). Requires
 * login (added 2026-09-02, alongside the "Refresh Jobs" button this
 * powers) - still a SHARED action affecting every user's data, not
 * scoped to whoever clicked it. Slow by nature - tens of seconds -
 * callers should show a loading state for the full duration.
 */
export function refreshJobs(token: string): Promise<RefreshSummary> {
  return request<RefreshSummary>("/refresh", { method: "POST", headers: authHeaders(token) });
}

/** POST /jobs/{id}/status - sets (or overwrites) this user's status on one job. */
export function setJobStatus(token: string, jobId: string, jobStatus: JobStatus): Promise<{ job_id: string; status: JobStatus }> {
  return request(`/jobs/${jobId}/status`, {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ status: jobStatus }),
  });
}

/** DELETE /jobs/{id}/status - clears this user's status on one job (the "toggle off" counterpart to setJobStatus, e.g. undoing an accidental Not Interested click). */
export function clearJobStatus(token: string, jobId: string): Promise<{ job_id: string; status: null }> {
  return request(`/jobs/${jobId}/status`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

/** GET /companies - admin-only; the full list backing CompaniesPage.tsx. */
export function fetchCompanies(token: string): Promise<CompanyOut[]> {
  return request<CompanyOut[]>("/companies", { headers: authHeaders(token) });
}

/** GET /companies/{id} - admin-only; what EditCompanyPage.tsx loads a company's current values from. */
export function fetchCompany(token: string, companyId: string): Promise<CompanyOut> {
  return request<CompanyOut>(`/companies/${companyId}`, { headers: authHeaders(token) });
}

/** POST /companies - admin-only (see api.py's get_current_admin); adds a company that starts getting fetched from the next Refresh Jobs onward. A non-admin token gets a 403, surfaced by request()'s normal error handling - same as any other failure. */
export function createCompany(token: string, payload: CreateCompanyPayload): Promise<CompanyOut> {
  return request<CompanyOut>("/companies", {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** PUT /companies/{id} - admin-only; edits an existing company's name/platform/slug. */
export function updateCompany(token: string, companyId: string, payload: CreateCompanyPayload): Promise<CompanyOut> {
  return request<CompanyOut>(`/companies/${companyId}`, {
    method: "PUT",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** DELETE /companies/{id} - admin-only; also removes that company's jobs (and any saved/applied/etc. status other users had on them) - see api.py's delete_company for why that cascade is necessary, not optional. */
export function deleteCompany(token: string, companyId: string): Promise<void> {
  return request<void>(`/companies/${companyId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

/** GET /jobs/{id}/score - admin-only; returns the admin's existing score for this job, or computes one lazily via scoring.py's score_job() on first call. */
export function fetchJobScore(token: string, jobId: string): Promise<JobScoreOut> {
  return request<JobScoreOut>(`/jobs/${jobId}/score`, { headers: authHeaders(token) });
}

/** PUT /jobs/{id}/score - admin-only; saves the admin's own corrected score/reasoning, marking it "reviewed" (see JobScoreSource in backend/models.py) - the real training signal, not the auto-generated baseline. */
export function saveJobScore(token: string, jobId: string, payload: SetJobScorePayload): Promise<JobScoreOut> {
  return request<JobScoreOut>(`/jobs/${jobId}/score`, {
    method: "PUT",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
