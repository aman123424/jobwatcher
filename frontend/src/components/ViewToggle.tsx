import type { JobView } from "../hooks/useJobsData";

interface ViewToggleProps {
  view: JobView;
  onChange: (view: JobView) => void;
}

const VIEWS: { value: JobView; label: string }[] = [
  { value: "all", label: "All Relevant" },
  { value: "best_match", label: "Best Match" },
];

/**
 * Two buttons, one active state - deliberately not a third component
 * per button (that would just be indirection with no real benefit at
 * this size). Reads the list of views from VIEWS above rather than
 * hardcoding two JSX blocks, so adding a view later is a one-line
 * change here instead of a copy-pasted button.
 */
export function ViewToggle({ view, onChange }: ViewToggleProps) {
  return (
    <div className="view-toggle" role="tablist">
      {VIEWS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={view === value}
          className={`view-toggle-button${view === value ? " active" : ""}`}
          onClick={() => onChange(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
