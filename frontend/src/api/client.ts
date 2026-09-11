import type {
  AuthResponse,
  CompanyOut,
  CreateCompanyPayload,
  JobScoreOut,
  JobsListResponse,
  JobStatus,
  LoginPayload,
  RefreshSummary,
  RegisterPayload,
  SetJobScorePayload,
  TailoringReportOut,
} from "./types";

/**
 * Thrown specifically for a 401 response - lets callers (see
 * useJobs.ts) tell "your session expired/is invalid, log in again"
 * apart from every other kind of failure (a genuine network error, a
 * 500, a validation error), which need different handling entirely.
 *
 * As of the refresh-token flow (added 2026-09-10), a plain 401 from an
 * AUTHENTICATED call no longer reaches a caller directly - request()
 * below tries one silent /auth/refresh first (see tryRefreshSession)
 * and retries. This is only ever thrown once that retry has also
 * failed (or wasn't attempted at all, e.g. a bad login/register), so
 * every existing `if (err instanceof UnauthorizedError) logout()` call
 * site still means exactly what it always meant: "there is no
 * recoverable session left, stop trying."
 */
export class UnauthorizedError extends Error {}

/**
 * Notified (see useAuth.tsx) whenever request() below silently
 * refreshes the session in the background - e.g. an access token
 * expired mid-use, not just the one deliberate bootstrap call on app
 * load. Lets AuthProvider's React state stay in sync with whatever
 * token is actually live, without client.ts needing to import React
 * itself just to hold that state.
 */
let onSessionRefreshed: ((auth: AuthResponse) => void) | null = null;
export function setSessionRefreshedHandler(handler: ((auth: AuthResponse) => void) | null): void {
  onSessionRefreshed = handler;
}

// Coalesces concurrent refresh attempts into ONE /auth/refresh call,
// not one per caller - e.g. several jobs-list calls 401ing at once
// because the access token expired while all of them were in flight
// would otherwise each try to rotate the SAME refresh token
// simultaneously, and only one of those racing calls could ever win
// (see auth.py's validate_and_rotate_refresh_token - a refresh token
// is only ever valid for exactly one use). Exported so useAuth.tsx's
// mount-time bootstrap call goes through this SAME guard, not a
// separate direct refreshSession() call - React 18 StrictMode
// double-invokes effects in development, which without this shared
// promise would fire two real, concurrent /auth/refresh requests
// carrying the identical not-yet-rotated cookie value, racing each
// other against the one-time-use rotation above.
let refreshInFlight: Promise<AuthResponse | null> | null = null;

export function tryRefreshSession(): Promise<AuthResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = refreshSession()
      .then((auth) => {
        onSessionRefreshed?.(auth);
        return auth;
      })
      .catch(() => null)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

/**
 * The backend's own address. Configurable via a .env file (Vite only
 * exposes env vars prefixed VITE_ - see .env.example in this project's
 * root) so this doesn't need a code change to point at a different
 * backend later (a deployed one, a different port, etc). Falls back to
 * "localhost:8000" (NOT "127.0.0.1:8000", even though `uvicorn api:app
 * --reload` binds the latter by default - see .env.example's own
 * comment for why: this frontend itself runs on "localhost", and a
 * browser treats "localhost"/"127.0.0.1" as different SITES for cookie
 * purposes, which would silently break the refresh-token cookie -
 * localhost still reaches the same uvicorn process either way).
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
// Paths that must NEVER trigger the retry-after-refresh logic below -
// a 401 from one of these already IS the final answer (wrong
// credentials, or the refresh call itself failing), not a stale
// access token that a refresh could fix. Retrying /auth/refresh on its
// OWN 401 would recurse forever.
const NO_REFRESH_RETRY_PATHS = new Set(["/auth/login", "/auth/register", "/auth/refresh"]);

async function request<T>(path: string, options?: RequestInit, _isRetryAfterRefresh = false): Promise<T> {
  let response: Response;
  try {
    // credentials: "include" - required on EVERY call, not just the
    // ones an Authorization header already covers: it's what makes the
    // browser (a) actually store the refresh-token cookie login/
    // register/refresh set via Set-Cookie, and (b) attach that cookie
    // back on /auth/refresh and /auth/logout. Harmless on every other
    // call - the cookie's own `path=/auth` (see backend/auth_routes.py)
    // means the browser only ever attaches it to those two endpoints
    // regardless of this flag.
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, credentials: "include" });
  } catch {
    // A network-level failure (backend not running, CORS blocked,
    // DNS/connection refused) never reaches response.ok below - it
    // throws before that.
    throw new Error(`Could not reach the backend at ${API_BASE_URL}. Is it running?`);
  }

  // A 401 on an AUTHENTICATED call (one that already sent an
  // Authorization header) most often just means the short-lived access
  // token expired mid-session, not that the user is actually logged
  // out - try one silent refresh and replay the exact same request
  // with the new token before giving up. `_isRetryAfterRefresh` caps
  // this at one attempt per call, so a refresh that succeeds but still
  // somehow leaves the retried call 401'ing falls through to the
  // normal error handling below instead of looping.
  const authHeader = (options?.headers as Record<string, string> | undefined)?.Authorization;
  if (response.status === 401 && authHeader && !_isRetryAfterRefresh && !NO_REFRESH_RETRY_PATHS.has(path)) {
    const refreshed = await tryRefreshSession();
    if (refreshed) {
      return request<T>(
        path,
        { ...options, headers: { ...options?.headers, Authorization: `Bearer ${refreshed.access_token}` } },
        true,
      );
    }
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
 * POST /auth/refresh - exchanges the HttpOnly refresh-token cookie
 * (attached by the browser automatically; this function never touches
 * its value) for a brand new access token, and rotates the cookie to a
 * new refresh token in the same move (see backend/auth.py's
 * validate_and_rotate_refresh_token). Called two ways: once by
 * AuthProvider on app load (see useAuth.tsx) to silently re-establish
 * a session after a reload - the access token itself never survives
 * one, on purpose, since it's kept in memory only - and internally by
 * request()'s tryRefreshSession() whenever an access token expires
 * mid-session. No request body and no Authorization header - the
 * refresh token IS the credential here, not the (already-expired or
 * nonexistent) access token.
 */
export function refreshSession(): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/refresh", { method: "POST" });
}

/**
 * POST /auth/logout - revokes the current refresh token server-side
 * and clears its cookie (see backend/auth_routes.py). A 204, so
 * request() returns undefined here - callers (useAuth.tsx) clear their
 * own in-memory token/user state separately regardless of whether this
 * call succeeds, since a failed logout request shouldn't strand
 * someone in a "still looks logged in" UI.
 */
export function logoutSession(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
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

/**
 * GET /jobs/{id}/tailoring-report - admin-only; returns this admin's
 * existing tailoring report for this job, or computes one lazily via
 * fitmodel (see backend/api.py's get_tailoring_report) on first call.
 * Throws a plain Error (via request()'s normal handling) whose message
 * is the backend's 503 detail when fitmodel isn't deployed yet - see
 * TailoringReportPage.tsx for how that's shown, not treated as a crash.
 */
export function fetchTailoringReport(token: string, jobId: string): Promise<TailoringReportOut> {
  return request<TailoringReportOut>(`/jobs/${jobId}/tailoring-report`, { headers: authHeaders(token) });
}
