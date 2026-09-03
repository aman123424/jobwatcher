import type { ChangeEvent } from "react";
import type { JobsTab } from "../hooks/useJobs";

interface JobsTabsProps {
  tab: JobsTab;
  onChange: (tab: JobsTab) => void;
}

const TABS: { value: JobsTab; label: string }[] = [
  { value: "all", label: "All Jobs" },
  { value: "new", label: "New Jobs" },
  { value: "mine", label: "My Jobs" },
  { value: "saved", label: "Saved Jobs" },
  { value: "rejected", label: "Rejected Jobs" },
  { value: "archived", label: "Archived Jobs" },
];

/** A dropdown, not a row of tab buttons (REWORKED 2026-09-03, Aman's own sketch) - six tabs as buttons would have wrapped or crowded the header; one <select> scales to however many tabs this ever grows to without a layout change. */
export function JobsTabs({ tab, onChange }: JobsTabsProps) {
  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    onChange(event.target.value as JobsTab);
  }

  return (
    <select className="select-input" value={tab} onChange={handleChange} aria-label="Jobs tab">
      {TABS.map(({ value, label }) => (
        <option key={value} value={value}>
          {label}
        </option>
      ))}
    </select>
  );
}
