import { useNavigate } from "react-router-dom";
import "./CompanyCard.scss";
import type { CompanyOut } from "../api/types";

interface CompanyCardProps {
  company: CompanyOut;
  onDelete: (company: CompanyOut) => void;
}

/** The platforms an admin can actually choose (see SelfServicePlatform's own docstring in api/types.ts) - every other real value (amazon/deshaw/atlassian/pcsx) is a one-off fetcher hardcoded to that one specific existing company, so there's no generic "platform name" worth showing for those - "Custom ATS" says what it is without implying it's a reusable, pickable option. */
const SELF_SERVICE_PLATFORMS = new Set(["greenhouse", "lever", "ashby", "smartrecruiters", "workday"]);

function platformLabel(platform: string): string {
  return SELF_SERVICE_PLATFORMS.has(platform) ? platform : "Custom ATS";
}

/** One company, on the admin /companies management page (CompaniesPage.tsx) - name, platform, and edit/delete actions. Presentational only, same split as JobCard.tsx: this reports what was clicked, the page owns what actually happens. */
export function CompanyCard({ company, onDelete }: CompanyCardProps) {
  const navigate = useNavigate();

  return (
    <article className="company-card">
      <div className="company-card-info">
        <h3 className="company-card-name">{company.name}</h3>
        <p className="company-card-platform">{platformLabel(company.platform)}</p>
      </div>
      <div className="company-card-actions">
        <button
          type="button"
          className="icon-button"
          aria-label={`Edit ${company.name}`}
          onClick={() => navigate(`/companies/${company.id}/edit`)}
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <button
          type="button"
          className="icon-button icon-button-danger"
          aria-label={`Delete ${company.name}`}
          onClick={() => onDelete(company)}
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M5 7h14M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-.8 12.1a1.5 1.5 0 0 1-1.5 1.4H8.3a1.5 1.5 0 0 1-1.5-1.4L6 7h12ZM10 11v6M14 11v6"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </article>
  );
}
