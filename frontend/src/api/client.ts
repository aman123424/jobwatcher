import type { AuthResponse, JobsListResponse, JobStatus, LoginPayload, RegisterPayload } from "./types";

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

/** GET /jobs - "All Jobs": every job posted in the last 24h (or of unknown age), with this user's own status attached where one exists. */
export function fetchAllJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs", { headers: authHeaders(token) });
}

/** GET /jobs/mine - "My Jobs": jobs this user marked Applied. No time filter. */
export function fetchMyJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/mine", { headers: authHeaders(token) });
}

/** GET /jobs/saved - "Saved Jobs": jobs this user marked Saved. No time filter. */
export function fetchSavedJobs(token: string): Promise<JobsListResponse> {
  return request<JobsListResponse>("/jobs/saved", { headers: authHeaders(token) });
}

/** POST /jobs/{id}/status - sets (or overwrites) this user's status on one job. */
export function setJobStatus(token: string, jobId: string, jobStatus: JobStatus): Promise<{ job_id: string; status: JobStatus }> {
  return request(`/jobs/${jobId}/status`, {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ status: jobStatus }),
  });
}
