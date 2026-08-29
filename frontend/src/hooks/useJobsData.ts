import { useCallback, useEffect, useState } from "react";
import { fetchAllJobs, fetchBestMatchJobs, refreshJobs } from "../api/client";
import type { JobMatch, JobsResponse } from "../api/types";

export type JobView = "all" | "best_match";

/**
 * Maps each view to the read-only GET call that serves it. Kept as one
 * lookup table rather than an if/else inside loadView below - adding a
 * third view later (if that ever happens) means adding one more entry
 * here, not touching the loading logic itself.
 */
const VIEW_FETCHERS: Record<JobView, () => Promise<JobsResponse>> = {
  all: fetchAllJobs,
  best_match: fetchBestMatchJobs,
};

/**
 * Owns every piece of state this app needs about jobs: which view is
 * active, the jobs themselves, when they were last refreshed, and the
 * two independent loading states (switching views is fast/cheap;
 * refreshing is slow - see refreshJobs()'s own docstring in client.ts -
 * so they're tracked separately rather than collapsed into one
 * "isLoading" flag that couldn't distinguish "near-instant view switch"
 * from "this might take 30-60 seconds").
 *
 * Pulling all of this into one hook (rather than scattering useState
 * calls across App.tsx directly) is what makes App.tsx itself stay a
 * pure composition of components - single responsibility: this hook
 * handles DATA, App.tsx handles LAYOUT.
 */
export function useJobsData() {
  const [view, setView] = useState<JobView>("all");
  const [jobs, setJobs] = useState<JobMatch[]>([]);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [isLoadingView, setIsLoadingView] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadView = useCallback(async (nextView: JobView) => {
    setIsLoadingView(true);
    setError(null);
    try {
      const data = await VIEW_FETCHERS[nextView]();
      setJobs(data.jobs);
      setUpdatedAt(data.updated_at);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs.");
    } finally {
      setIsLoadingView(false);
    }
  }, []);

  // Load whichever view is active on first mount, and again any time
  // the user switches views - so switching to "Best Match" always
  // reflects the latest cached data, and a page reload immediately
  // shows whatever the backend already has cached (if POST /refresh
  // was called in an earlier session) instead of starting blank.
  useEffect(() => {
    // oxlint's set-state-in-effect rule flags this, but it's warning
    // about a DIFFERENT, genuinely risky pattern (calling setState
    // synchronously in the effect body itself, causing an extra
    // render on every render). This is the standard "fetch on mount /
    // on dependency change" idiom instead - loadView's setState calls
    // all happen inside an async callback, after this effect has
    // already returned, which is exactly what useEffect is for
    // (synchronizing this component with the external system that is
    // the backend's cached job list).
    // oxlint-disable-next-line react/set-state-in-effect
    void loadView(view);
  }, [view, loadView]);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      // POST /refresh's own response already has the fresh data, but
      // it's always the UNFILTERED "all" list (see api.py) - re-running
      // loadView(view) afterwards, rather than using this response
      // directly, means "Best Match" stays correctly filtered without
      // this hook needing to duplicate the backend's own MIN_SCORE
      // filtering logic on the frontend.
      await refreshJobs();
      await loadView(view);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setIsRefreshing(false);
    }
  }, [view, loadView]);

  return { view, setView, jobs, updatedAt, isLoadingView, isRefreshing, error, refresh };
}
