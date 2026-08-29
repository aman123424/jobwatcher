interface RefreshBarProps {
  updatedAt: string | null;
  isRefreshing: boolean;
  onRefresh: () => void;
}

/**
 * Turns the backend's raw ISO 8601 UTC timestamp into something
 * readable in the viewer's own local time - the backend deliberately
 * doesn't pre-format this (unlike job_posted_date, which IS pre-
 * formatted server-side into IST - see api.py's _normalize_posted_date)
 * because "last refreshed" is about THIS reader's clock, not a fixed
 * IST audience the way job posting times are.
 */
function formatUpdatedAt(updatedAt: string | null): string {
  if (!updatedAt) {
    return "Never refreshed yet";
  }
  return `Last refreshed ${new Date(updatedAt).toLocaleString()}`;
}

/**
 * The one control that triggers a real backend fetch (POST /refresh -
 * see client.ts). Single responsibility: show the button, show when
 * data was last refreshed, and reflect the in-flight state - it has no
 * opinion about what "jobs" or "view" even are, so it doesn't need to
 * change if either of those evolve.
 */
export function RefreshBar({ updatedAt, isRefreshing, onRefresh }: RefreshBarProps) {
  return (
    <div className="refresh-bar">
      <button
        type="button"
        className="refresh-button"
        onClick={onRefresh}
        disabled={isRefreshing}
      >
        {isRefreshing ? "Fetching fresh jobs…" : "Fetch Fresh"}
      </button>
      <span className="updated-at">{formatUpdatedAt(updatedAt)}</span>
    </div>
  );
}
