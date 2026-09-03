import { useTheme } from "../hooks/useTheme";

/**
 * A single pill-shaped button, not two separate buttons - moon fixed
 * on the left, sun fixed on the right, with a sliding thumb behind
 * whichever one is currently active. Clicking anywhere on it flips
 * `theme` (see useTheme.tsx) - there's only one state to toggle, so
 * one click target is simpler than making each icon its own button.
 */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggleTheme}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      aria-pressed={theme === "dark"}
    >
      <span className={`theme-toggle-thumb${theme === "light" ? " theme-toggle-thumb-right" : ""}`} />
      <svg className="theme-toggle-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"
          fill="currentColor"
        />
      </svg>
      <svg className="theme-toggle-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="4.5" fill="currentColor" />
        <g stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <path d="M12 2.5v2.4M12 19.1v2.4M21.5 12h-2.4M4.9 12H2.5" />
          <path d="M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7M18.5 18.5l-1.7-1.7M7.2 7.2 5.5 5.5" />
        </g>
      </svg>
    </button>
  );
}
