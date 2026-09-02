import { useCallback, useEffect, useState } from "react";
import {
  UnauthorizedError,
  fetchAllJobs,
  fetchArchivedJobs,
  fetchMyJobs,
  fetchSavedJobs,
  refreshJobs,
  setJobStatus,
} from "../api/client";
import type { JobOut, JobStatus, JobsListResponse } from "../api/types";
import { useAuth } from "./useAuth";

export type JobsTab = "all" | "mine" | "saved" | "archived";

/** Maps each tab to the GET call that serves it - one lookup table rather than an if/else, so adding another tab later (e.g. "Good Matches") is a one-line addition here, not a change to the loading logic itself. */
const TAB_FETCHERS: Record<JobsTab, (token: string) => Promise<JobsListResponse>> = {
  all: fetchAllJobs,
  mine: fetchMyJobs,
  saved: fetchSavedJobs,
  archived: fetchArchivedJobs,
};

/** What status a job needs to have to belong on each non-"all" tab - "all" itself isn't here since it shows every job regardless of status. */
const TAB_STATUS: Record<Exclude<JobsTab, "all">, JobStatus> = {
  mine: "applied",
  saved: "saved",
  archived: "not_interested",
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
        // Update local state directly instead of re-fetching the whole
        // tab (FIXED 2026-09-02 - a real bug Aman caught: re-fetching
        // briefly showed JobList's "Loading…" placeholder, collapsing
        // the page's height and forcing the browser to reset scroll
        // position, since there was nothing left to scroll TO for a
        // moment. A local update never removes the list from the DOM
        // at all, so there's nothing to reset scroll against - and
        // it's also just cheaper, no extra round-trip to the backend.
        //
        // "all" keeps every job, just updates the one that changed.
        // Every other tab only keeps a job if its NEW status still
        // matches what that tab shows (see TAB_STATUS above) -
        // otherwise the job no longer belongs here and disappears,
        // the same real behavior as before, just computed locally.
        setJobs((prev) => {
          if (tab === "all") {
            return prev.map((j) => (j.job_id === jobId ? { ...j, status } : j));
          }
          if (status === TAB_STATUS[tab]) {
            return prev.map((j) => (j.job_id === jobId ? { ...j, status } : j));
          }
          return prev.filter((j) => j.job_id !== jobId);
        });
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to update status.");
      }
    },
    [token, tab, logout],
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
      // fresh results. Unlike updateStatus above, a full reload here
      // is correct, not a bug - the whole point of refreshing is
      // pulling in a real, possibly very different set of jobs.
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
