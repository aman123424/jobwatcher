import "./AppHeader.scss";
import { AvatarMenu } from "./AvatarMenu";
import { ThemeToggle } from "./ThemeToggle";
import { useAuth } from "../hooks/useAuth";

/**
 * The "JobWatcher" title + theme toggle + avatar dropdown row - shared
 * across every logged-in page (JobsPage, CompaniesPage), extracted
 * 2026-09-04 when CompaniesPage needed the exact same header instead
 * of a second copy of this markup drifting from JobsPage's over time.
 */
export function AppHeader() {
  const { user } = useAuth();

  return (
    <header className="jobs-page-header">
      <h1>JobWatcher</h1>
      <div className="jobs-page-header-right">
        <ThemeToggle />
        {user && <AvatarMenu name={user.name} />}
      </div>
    </header>
  );
}
