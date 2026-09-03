import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { SelfServicePlatform } from "../api/types";

/** See SelfServicePlatform's own docstring in api/types.ts for why this list is narrower than every platform fetchers.py knows how to fetch. */
const PLATFORMS: SelfServicePlatform[] = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday"];

interface CompanyFormProps {
  title: string;
  companyName: string;
  onCompanyNameChange: (value: string) => void;
  platform: SelfServicePlatform;
  onPlatformChange: (value: SelfServicePlatform) => void;
  slug: string;
  onSlugChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  isSubmitting: boolean;
  submitLabel: string;
  submittingLabel: string;
  error: string | null;
  success: string | null;
}

/**
 * The name/platform/slug form shared by AddCompanyPage (POST) and
 * EditCompanyPage (PUT) - identical fields either way, only the
 * submit action, labels, and initial values differ, which the two
 * pages own themselves rather than duplicating this markup twice.
 */
export function CompanyForm({
  title,
  companyName,
  onCompanyNameChange,
  platform,
  onPlatformChange,
  slug,
  onSlugChange,
  onSubmit,
  isSubmitting,
  submitLabel,
  submittingLabel,
  error,
  success,
}: CompanyFormProps) {
  const navigate = useNavigate();

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={onSubmit}>
        <h1>{title}</h1>

        <label>
          Company name
          <input type="text" value={companyName} onChange={(e) => onCompanyNameChange(e.target.value)} required />
        </label>

        <label>
          Platform
          <select
            className="select-input"
            value={platform}
            onChange={(e) => onPlatformChange(e.target.value as SelfServicePlatform)}
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
          <input type="text" value={slug} onChange={(e) => onSlugChange(e.target.value)} required />
        </label>
        <p className="auth-subtitle">
          The platform-specific identifier used to fetch this company's board - a plain board slug for most
          platforms, but a compound "|"-separated string for a few (e.g. Workday's "tenant|wdN|site").
        </p>

        {error && <p className="auth-error">{error}</p>}
        {success && <p className="auth-success">{success}</p>}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? submittingLabel : submitLabel}
        </button>

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
      </form>
    </div>
  );
}
