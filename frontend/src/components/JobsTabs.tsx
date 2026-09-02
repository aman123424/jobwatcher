import type { JobsTab } from "../hooks/useJobs";

interface JobsTabsProps {
  tab: JobsTab;
  onChange: (tab: JobsTab) => void;
}

const TABS: { value: JobsTab; label: string }[] = [
  { value: "all", label: "All Jobs" },
  { value: "mine", label: "My Jobs" },
  { value: "saved", label: "Saved Jobs" },
  { value: "archived", label: "Archived Jobs" },
];

export function JobsTabs({ tab, onChange }: JobsTabsProps) {
  return (
    <div className="jobs-tabs" role="tablist">
      {TABS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={tab === value}
          className={`jobs-tab-button${tab === value ? " active" : ""}`}
          onClick={() => onChange(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
