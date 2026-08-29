import type { JobsResponse } from "./types";

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
 * Shared request helper - every function below (fetchAllJobs,
 * fetchBestMatchJobs, refreshJobs) goes through this one place rather
 * than each repeating its own fetch()/error-handling logic (DRY: one
 * definition of "how do we call the backend and what counts as
 * failure", not three near-identical copies that could drift apart).
 *
 * Throws on any non-2xx response or network failure, rather than
 * returning some sentinel value - lets callers use ordinary
 * try/catch (see useJobsData.ts) instead of checking a boolean/null
 * result after every single call.
 */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options);
  } catch {
    // A network-level failure (backend not running, CORS blocked,
    // DNS/connection refused) never reaches response.ok below - it
    // throws before that. Re-thrown here with a message a non-technical
    // reader (this is Aman's own tool) can act on immediately.
    throw new Error(
      `Could not reach the backend at ${API_BASE_URL}. Is it running? (uvicorn api:app --reload)`,
    );
  }

  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as T;
}

/** GET /jobs - every relevant job from the last refresh, any score. No new fetch triggered. */
export function fetchAllJobs(): Promise<JobsResponse> {
  return request<JobsResponse>("/jobs");
}

/** GET /jobs/best_match - same cached data, narrowed to match_score >= MIN_SCORE. No new fetch triggered. */
export function fetchBestMatchJobs(): Promise<JobsResponse> {
  return request<JobsResponse>("/jobs/best_match");
}

/**
 * POST /refresh - the ONLY call that actually fetches live data across
 * every company (see api.py's own docstring for why). Slow by nature -
 * a few tens of seconds - callers should show a loading state for the
 * full duration of this call, not just a brief spinner.
 */
export function refreshJobs(): Promise<JobsResponse> {
  return request<JobsResponse>("/refresh", { method: "POST" });
}
