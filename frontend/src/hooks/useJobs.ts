import { useCallback, useEffect, useState } from "react";
import {
  UnauthorizedError,
  clearJobStatus,
  fetchAllJobs,
  fetchArchivedJobs,
  fetchMyJobs,
  fetchNewJobs,
  fetchRejectedJobs,
  fetchSavedJobs,
  refreshJobs,
  setJobStatus,
} from "../api/client";
import type { JobOut, JobStatus, JobsListResponse } from "../api/types";
import { useAuth } from "./useAuth";

export type JobsTab = "all" | "new" | "mine" | "saved" | "rejected" | "archived";

/** Maps each tab to the GET call that serves it - one lookup table rather than an if/else, so adding another tab later (e.g. "Good Matches") is a one-line addition here, not a change to the loading logic itself. */
const TAB_FETCHERS: Record<JobsTab, (token: string) => Promise<JobsListResponse>> = {
  all: fetchAllJobs,
  new: fetchNewJobs,
  mine: fetchMyJobs,
  saved: fetchSavedJobs,
  rejected: fetchRejectedJobs,
  archived: fetchArchivedJobs,
};

/**
 * What status a job needs to have to belong on each non-"all" tab -
 * "all" itself isn't here since it shows every job regardless of
 * status. "new" maps to `null` (no status at all, not a fourth real
 * JobStatus value - see UserJob's own docstring in models.py) rather
 * than being left out of this table, so updateStatus below can treat
 * every non-"all" tab identically: still belongs here once its status
 * matches TAB_STATUS[tab], gone otherwise - "new" included, no
 * special-casing needed.
 */
const TAB_STATUS: Record<Exclude<JobsTab, "all">, JobStatus | null> = {
  new: null,
  mine: "applied",
  saved: "saved",
  rejected: "rejected",
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
  // A SEPARATE error slot from `error` above, deliberately - `error`
  // gates JobList's whole render (see JobList.tsx: it shows an error
  // message INSTEAD of the list), which is correct when the list
  // itself failed to load, but very wrong for a single optimistic
  // status update failing in the background - that should roll back
  // just that one job and show a small dismissable notice, not blank
  // out a list of jobs the user is still actively looking at.
  const [statusError, setStatusError] = useState<string | null>(null);
  // A shared/global value straight from the backend (see
  // JobsListResponse in api/types.ts) - every jobs-listing endpoint
  // returns it, so it stays current after every tab switch too, not
  // just right after clicking Refresh.
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);

  const loadTab = useCallback(
    async (nextTab: JobsTab) => {
      if (!token) return;
      setIsLoading(true);
      setError(null);
      setStatusError(null);
      try {
        const data = await TAB_FETCHERS[nextTab](token);
        setJobs(data.jobs);
        setLastRefreshedAt(data.last_refreshed_at);
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
    (jobId: string, status: JobStatus | null) => {
      if (!token) return;
      const index = jobs.findIndex((j) => j.job_id === jobId);
      if (index === -1) return;
      const originalJob = jobs[index];

      // The caller (JobCard's status dropdown, or its tab-specific
      // Rejected/Mark as Applied button - see JobCard.tsx) always
      // states its intent explicitly now: a real JobStatus to SET, or
      // `null` to CLEAR back to no status at all (picking "No status"
      // from the dropdown). No more auto-detecting "clicking the same
      // button again means clear" (REWORKED 2026-09-03, replacing the
      // three separate status BUTTONS with one <select> - a native
      // dropdown doesn't fire a change event for re-selecting the
      // option that's already chosen, so that old convention couldn't
      // carry over as-is; making intent explicit is also just clearer).
      //
      // OPTIMISTIC UPDATE (Aman's own call - "just like Instagram's
      // like button"): the UI changes THE INSTANT the dropdown/button
      // is used, not after the API call resolves. This is also what
      // fixed a real scroll-position bug Aman caught earlier
      // (re-fetching the tab briefly showed a "Loading…" placeholder,
      // collapsing the page and resetting scroll) - updating local
      // state directly never removes the list from the DOM at all.
      //
      // "all" keeps every job, just updates the one that changed.
      // Every other tab only keeps a job if its NEW status still
      // matches what that tab shows (see TAB_STATUS above) - a clear,
      // or a switch to a different status, never matches any tab's
      // own status, so it naturally falls through to the same "no
      // longer belongs here" removal.
      setJobs((prev) => {
        if (tab === "all") {
          return prev.map((j) => (j.job_id === jobId ? { ...j, status } : j));
        }
        if (status === TAB_STATUS[tab]) {
          return prev.map((j) => (j.job_id === jobId ? { ...j, status } : j));
        }
        return prev.filter((j) => j.job_id !== jobId);
      });

      // The actual API call happens IN THE BACKGROUND, deliberately
      // not awaited before the UI update above - callers don't wait on
      // this promise either, so a slow network never blocks the
      // dropdown/button from feeling instant.
      setStatusError(null);
      const request = status === null ? clearJobStatus(token, jobId) : setJobStatus(token, jobId, status);
      request.catch((err) => {
        // The backend call failed - undo exactly this one optimistic
        // change (put the job's status, or the job itself if the
        // update had removed it from this tab, back the way it was)
        // rather than reverting to a stale full-list snapshot, which
        // would also wipe out any OTHER status change the user made on
        // a different job while this request was still in flight.
        setJobs((prev) => {
          if (prev.some((j) => j.job_id === jobId)) {
            return prev.map((j) => (j.job_id === jobId ? originalJob : j));
          }
          const restored = [...prev];
          restored.splice(Math.min(index, restored.length), 0, originalJob);
          return restored;
        });
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setStatusError(err instanceof Error ? err.message : "Failed to update status.");
      });
    },
    [token, tab, jobs, logout],
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

  return { tab, setTab, jobs, isLoading, isRefreshing, error, statusError, updateStatus, refresh, lastRefreshedAt };
}
