import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createCompany, UnauthorizedError } from "../api/client";
import type { Platform } from "../api/types";
import { useAuth } from "../hooks/useAuth";

/**
 * Every platform fetchers.py actually knows how to fetch - mirrors
 * backend/models.py's Platform enum exactly. A plain text input for
 * platform would let an admin create a company the backend can NEVER
 * fetch (see api.py's CreateCompanyRequest for the same reasoning
 * server-side) - a dropdown of only the real options closes that off
 * here too, not just at the API boundary.
 */
const PLATFORMS: Platform[] = [
  "greenhouse",
  "lever",
  "ashby",
  "smartrecruiters",
  "workday",
  "pcsx",
  "amazon",
  "deshaw",
  "atlassian",
];

/**
 * Admin-only page (see ProtectedRoute's admin check in App.tsx) for
 * adding a company to the shared `companies` table - the button that
 * links here (AvatarMenu/JobsPage.tsx) only ever shows for an admin
 * anyway, but this page still doesn't trust that alone (a non-admin
 * hitting this URL directly still gets a real 403 from POST
 * /companies, see api.py's get_current_admin).
 */
export function AddCompanyPage() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState("");
  const [platform, setPlatform] = useState<Platform>("greenhouse");
  const [slug, setSlug] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await createCompany(token, { company_name: companyName, platform, slug });
      setSuccess(`${result.name} added - it'll be included from the next Refresh Jobs onward.`);
      setCompanyName("");
      setSlug("");
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setError("Your session has expired - log in again.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to add company.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Add company</h1>
        <p className="auth-subtitle">Fetched starting the next Refresh Jobs - no redeploy needed.</p>

        <label>
          Company name
          <input
            type="text"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            required
          />
        </label>

        <label>
          Platform
          <select value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label>
          Slug
          <input type="text" value={slug} onChange={(e) => setSlug(e.target.value)} required />
        </label>
        <p className="auth-subtitle">
          The platform-specific identifier used to fetch this company's board - a plain board slug for most
          platforms, but a compound "|"-separated string for a few (e.g. Workday's "tenant|wdN|site").
        </p>

        {error && <p className="auth-error">{error}</p>}
        {success && <p className="auth-success">{success}</p>}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Adding…" : "Add company"}
        </button>

        <p className="auth-switch">
          <a href="/" onClick={(e) => { e.preventDefault(); navigate("/"); }}>
            ← Back to jobs
          </a>
        </p>
      </form>
    </div>
  );
}
