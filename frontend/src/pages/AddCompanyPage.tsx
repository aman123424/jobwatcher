import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createCompany, UnauthorizedError } from "../api/client";
import type { SelfServicePlatform } from "../api/types";
import { useAuth } from "../hooks/useAuth";

/** See SelfServicePlatform's own docstring in api/types.ts for why this list is narrower than every platform fetchers.py knows how to fetch. */
const PLATFORMS: SelfServicePlatform[] = [
  "greenhouse",
  "lever",
  "ashby",
  "smartrecruiters",
  "workday",
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
  const [platform, setPlatform] = useState<SelfServicePlatform>("greenhouse");
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
      const result = await createCompany(token, {
        company_name: companyName,
        platform,
        slug,
      });
      setSuccess(
        `${result.name} added - it'll be included from the next Refresh Jobs onward.`,
      );
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
          <select
            className="select-input"
            value={platform}
            onChange={(e) => setPlatform(e.target.value as SelfServicePlatform)}
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label>
          Slug
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
          />
        </label>

        {error && <p className="auth-error">{error}</p>}
        {success && <p className="auth-success">{success}</p>}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Adding…" : "Add company"}
        </button>

        <p className="auth-switch">
          <a
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            ← Back to jobs
          </a>
        </p>
      </form>
    </div>
  );
}
