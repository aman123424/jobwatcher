import { useState, type FormEvent } from "react";
import { CompanyForm } from "../components/CompanyForm";
import { createCompany, UnauthorizedError } from "../api/client";
import type { SelfServicePlatform } from "../api/types";
import { useAuth } from "../hooks/useAuth";

/**
 * Admin-only page (see ProtectedRoute's admin check in App.tsx) for
 * adding a company to the shared `companies` table - reached from the
 * /companies management page's "+ Add Company" button now (moved off
 * the jobs page, 2026-09-04), but this page still doesn't trust that
 * button alone (a non-admin hitting this URL directly still gets a
 * real 403 from POST /companies, see api.py's get_current_admin).
 */
export function AddCompanyPage() {
  const { token } = useAuth();
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
    <CompanyForm
      title="Add company"
      companyName={companyName}
      onCompanyNameChange={setCompanyName}
      platform={platform}
      onPlatformChange={setPlatform}
      slug={slug}
      onSlugChange={setSlug}
      onSubmit={handleSubmit}
      isSubmitting={isSubmitting}
      submitLabel="Add company"
      submittingLabel="Adding…"
      error={error}
      success={success}
    />
  );
}
