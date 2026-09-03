import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { CompanyCard } from "../components/CompanyCard";
import { deleteCompany, fetchCompanies, UnauthorizedError } from "../api/client";
import type { CompanyOut } from "../api/types";
import { useAuth } from "../hooks/useAuth";

/**
 * Admin-only company management (see App.tsx's adminOnly route) -
 * same page shell as JobsPage (AppHeader, a top action row, a search
 * row, then a list), but for `companies` instead of `jobs`: "+ Add
 * Company" replaces "Refresh Jobs" in the top row (Aman's own
 * placement, 2026-09-04 - this page IS the admin area, so unlike the
 * old button on the jobs page, no separate is_admin check is needed
 * here beyond the route itself already requiring it), and each row is
 * a CompanyCard (name, platform, edit/delete) instead of a JobCard.
 */
export function CompaniesPage() {
  const { token, logout } = useAuth();
  const [companies, setCompanies] = useState<CompanyOut[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await fetchCompanies(token);
        if (!cancelled) setCompanies(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load companies.");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, logout]);

  async function handleDelete(company: CompanyOut) {
    if (!token) return;
    // A real confirm, not a silently-reversible action - deleting a
    // company cascades to its jobs AND every user's saved/applied/etc.
    // status on those jobs (see api.py's delete_company).
    const confirmed = window.confirm(
      `Delete ${company.name}? This also removes its jobs and any saved/applied status other users have on them.`,
    );
    if (!confirmed) return;

    const previousCompanies = companies;
    setCompanies((prev) => prev.filter((c) => c.id !== company.id));
    setError(null);
    try {
      await deleteCompany(token, company.id);
    } catch (err) {
      setCompanies(previousCompanies);
      if (err instanceof UnauthorizedError) {
        logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to delete company.");
    }
  }

  const filteredCompanies = search.trim()
    ? companies.filter((c) => c.name.toLowerCase().includes(search.trim().toLowerCase()))
    : companies;

  return (
    <div className="jobs-page">
      <AppHeader />

      <div className="refresh-row">
        <Link to="/add-company" className="refresh-button">
          + Add Company
        </Link>
      </div>

      <div className="jobs-filter-row">
        <input
          type="text"
          className="company-search-input"
          placeholder="Search companies"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search companies"
        />
      </div>

      {error && <p className="status-error-banner">{error}</p>}

      <main>
        {isLoading ? (
          <p className="job-list-status">Loading…</p>
        ) : filteredCompanies.length === 0 ? (
          <p className="job-list-status">
            {search.trim() ? `No companies match "${search.trim()}".` : "No companies yet."}
          </p>
        ) : (
          <div className="job-list">
            {filteredCompanies.map((company) => (
              <CompanyCard key={company.id} company={company} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
