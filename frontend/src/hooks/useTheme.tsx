import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "jobwatcher_theme";

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * The user's own EXPLICIT choice, if they ever toggled - distinct from
 * index.css's `prefers-color-scheme` media query, which only reflects
 * the OS/browser's setting. Wrapped in try/catch for the same reason
 * useAuth.tsx's loadStoredSession() is - a private-browsing tab can
 * make localStorage throw, not just return empty.
 */
function loadStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}

function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Degraded experience (won't remember the choice across a reload),
    // not a crash - same reasoning as useAuth.tsx's saveSession().
  }
}

/**
 * No stored preference yet (first visit, or storage unavailable) -
 * falls back to whatever the OS/browser already prefers, so a first-
 * time visitor gets a sensible default without being forced to pick.
 */
function systemPrefersDark(): boolean {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

/**
 * Wraps the whole app (see App.tsx), same pattern as AuthProvider -
 * any component can read/toggle the theme via useTheme() below without
 * prop-drilling. The actual light/dark CSS values live in index.css as
 * custom properties; this only ever sets `data-theme` on <html> - one
 * single source of truth for "which theme is active" that both CSS
 * (via the `:root[data-theme=...]` selectors) and React read from.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => loadStoredTheme() ?? (systemPrefersDark() ? "dark" : "light"));

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    saveTheme(theme);
  }, [theme]);

  function toggleTheme() {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

// Same Fast-Refresh tradeoff useAuth.tsx already accepts - see its own comment.
// oxlint-disable-next-line react/only-export-components
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme() must be used inside <ThemeProvider>");
  }
  return ctx;
}
