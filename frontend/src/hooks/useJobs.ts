import { useCallback, useEffect, useState } from "react";
import { UnauthorizedError, fetchAllJobs, fetchMyJobs, fetchSavedJobs, refreshJobs, setJobStatus } from "../api/client";
import type { JobOut, JobStatus, JobsListResponse } from "../api/types";
import { useAuth } from "./useAuth";

export type JobsTab = "all" | "mine" | "saved";

/** Maps each tab to the GET call that serves it - one lookup table rather than an if/else, so adding a fourth tab later (e.g. "Good Matches") is a one-line addition here, not a change to the loading logic itself. */
const TAB_FETCHERS: Record<JobsTab, (token: string) => Promise<JobsListResponse>> = {
  all: fetchAllJobs,
  mine: fetchMyJobs,
  saved: fetchSavedJobs,
};

/**
 * Owns everything the jobs page needs: which tab is active, that
 * tab's jobs, loading/error state, updating a job's status, and
 * triggering a refresh.
 *
 * TWO SEPARATE LOADING FLAGS, DELIBERATELY: switching tabs
 * (`isLoading`) is a near-instant read; triggering `/refresh`
 * (`isRefreshing`) is a real live fetch across every company - tens
 * of seconds. Collapsing them into one flag couldn't distinguish "this
 * will be back in a moment" from "this might take a while", which
 * matters for what the UI should actually show while each is in flight.
 */
export function useJobs() {
  const { token, logout } = useAuth();
  const [tab, setTab] = useState<JobsTab>("all");
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTab = useCallback(
    async (nextTab: JobsTab) => {
      if (!token) return;
      setIsLoading(true);
      setError(null);
      try {
        const data = await TAB_FETCHERS[nextTab](token);
        setJobs(data.jobs);
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          // The token's expired or otherwise invalid - logout() clears
          // it, and ProtectedRoute (which already watches this same
          // token) redirects to /login on its own next render, no
          // navigate() call needed here.
          logout();
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load jobs.");
      } finally {
        setIsLoading(false);
      }
    },
    [token, logout],
  );

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void loadTab(tab);
  }, [tab, loadTab]);

  const updateStatus = useCallback(
    async (jobId: string, status: JobStatus) => {
      if (!token) return;
      try {
        await setJobStatus(token, jobId, status);
        // Re-fetch the CURRENT tab rather than mutating local state by
        // hand - simpler, and correctly handles every case at once:
        // on "All Jobs" the job stays visible with an updated status
        // badge; on "My Jobs"/"Saved Jobs", a status change AWAY from
        // that tab's own status correctly makes the job disappear from
        // view, matching the real, permanent Applied<->Saved<->Not
        // Interested transition rules a single status field enforces.
        await loadTab(tab);
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to update status.");
      }
    },
    [token, tab, loadTab, logout],
  );

  const refresh = useCallback(async () => {
    if (!token) return;
    setIsRefreshing(true);
    setError(null);
    try {
      await refreshJobs(token);
      // The refresh itself doesn't return per-user data (it's a
      // shared action, see refreshJobs()'s own docstring) - reload
      // whichever tab is currently showing so the UI reflects the
      // fresh results.
      await loadTab(tab);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setIsRefreshing(false);
    }
  }, [token, tab, loadTab, logout]);

  return { tab, setTab, jobs, isLoading, isRefreshing, error, updateStatus, refresh };
}
