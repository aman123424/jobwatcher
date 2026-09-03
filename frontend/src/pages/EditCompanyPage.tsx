import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CompanyForm } from "../components/CompanyForm";
import { fetchCompany, updateCompany, UnauthorizedError } from "../api/client";
import type { SelfServicePlatform } from "../api/types";
import { useAuth } from "../hooks/useAuth";

/**
 * Admin-only (see App.tsx). Loads the company FRESH by id (GET
 * /companies/{id}) rather than relying on data passed through
 * navigation, so a direct URL visit or a page reload both still work,
 * not just arriving here by clicking the edit icon on CompaniesPage.
 *
 * A company whose CURRENT platform isn't one of the five self-service
 * ones (i.e. one of the original amazon/deshaw/atlassian/pcsx rows -
 * see SelfServicePlatform's own docstring) can't be represented in
 * this form's dropdown at all - editing those stays a direct-database
 * action, the same known limitation PUT /companies/{id} itself
 * documents server-side. This page doesn't special-case that; the
 * dropdown just falls back to "greenhouse" as a starting point, and
 * saving would repoint that company at a different platform, same as
 * any other edit.
 */
export function EditCompanyPage() {
  const { id } = useParams<{ id: string }>();
  const { token, logout } = useAuth();
  const navigate = useNavigate();

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [platform, setPlatform] = useState<SelfServicePlatform>("greenhouse");
  const [slug, setSlug] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !id) return;
    let cancelled = false;
    (async () => {
      try {
        const company = await fetchCompany(token, id);
        if (cancelled) return;
        setCompanyName(company.name);
        setSlug(company.slug);
        // See this component's own docstring - a non-self-service
        // platform has no matching <option>, so the dropdown falls
        // back to its own default rather than showing nothing selected.
        const knownPlatforms: SelfServicePlatform[] = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday"];
        if ((knownPlatforms as string[]).includes(company.platform)) {
          setPlatform(company.platform as SelfServicePlatform);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setLoadError(err instanceof Error ? err.message : "Failed to load company.");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, id, logout]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token || !id) return;
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await updateCompany(token, id, { company_name: companyName, platform, slug });
      setSuccess(`${result.name} updated.`);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setError("Your session has expired - log in again.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to update company.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) {
    return <p className="job-list-status">Loading…</p>;
  }

  if (loadError) {
    return (
      <div className="jobs-page">
        <p className="job-list-status job-list-error">{loadError}</p>
        <p className="auth-switch">
          <a
            href="/companies"
            onClick={(e) => {
              e.preventDefault();
              navigate("/companies");
            }}
          >
            ← Back to companies
          </a>
        </p>
      </div>
    );
  }

  return (
    <CompanyForm
      title="Edit company"
      companyName={companyName}
      onCompanyNameChange={setCompanyName}
      platform={platform}
      onPlatformChange={setPlatform}
      slug={slug}
      onSlugChange={setSlug}
      onSubmit={handleSubmit}
      isSubmitting={isSubmitting}
      submitLabel="Save changes"
      submittingLabel="Saving…"
      error={error}
      success={success}
    />
  );
}
