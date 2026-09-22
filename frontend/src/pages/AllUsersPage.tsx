import { useEffect, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { fetchUsers, UnauthorizedError } from "../api/client";
import type { UserOut } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import "./AllUsersPage.scss";

/**
 * Admin-only (see App.tsx's route, gated adminOnly - same real
 * server-side gate too, GET /users requires get_current_admin) -
 * "All Users" in AvatarMenu.tsx navigates here. Same page shell as
 * CompaniesPage (AppHeader, then the list), but a plain table instead
 * of a card list - a name/email/tier/resume_url row per user has no
 * per-row actions (unlike CompanyCard's edit/delete), so a table is
 * the more direct fit than reusing the card pattern here.
 */
export function AllUsersPage() {
  const { token, logout } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await fetchUsers(token);
        if (!cancelled) setUsers(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load users.");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, logout]);

  return (
    <div className="jobs-page">
      <AppHeader />

      <div>Total number of users: {users.length}</div>

      {error && <p className="status-error-banner">{error}</p>}

      <main>
        {isLoading ? (
          <p className="job-list-status">Loading…</p>
        ) : users.length === 0 ? (
          <p className="job-list-status">No users yet.</p>
        ) : (
          <div className="users-table-wrap">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Tier</th>
                  <th>Resume</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.email}>
                    <td>{u.name}</td>
                    <td>{u.email}</td>
                    <td className="users-table-tier">{u.tier}</td>
                    <td>
                      {u.resume_url ? (
                        <a href={u.resume_url} target="_blank" rel="noreferrer">
                          View
                        </a>
                      ) : (
                        <span className="users-table-empty">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
