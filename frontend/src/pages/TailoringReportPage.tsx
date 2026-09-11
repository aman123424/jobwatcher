import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import "./TailoringReportPage.scss";
import { fetchTailoringReport, UnauthorizedError } from "../api/client";
import type { TailoringSuggestionOut } from "../api/types";
import { useAuth } from "../hooks/useAuth";

const TYPE_LABELS: Record<TailoringSuggestionOut["type"], string> = {
  true_gap: "Not on your resume",
  unverified: "Listed, but unverified",
  wording_mismatch: "Different wording",
};

/**
 * Admin-only (see App.tsx), sibling to JobScorePage - reached via a
 * link from there rather than its own badge on JobCard, keeping
 * JobScorePage as the one hub for "everything about how well I match
 * this job" (see the implementation plan this shipped from).
 *
 * Same LAZY compute-on-first-view pattern as the score page: the
 * first visit may take a while (fitmodel's embedding model can take
 * 20-30s+ on a cold start - see backend/api.py's
 * FITMODEL_REQUEST_TIMEOUT_SECONDS) - shown as a loading state, not a
 * spinner that looks stuck. A 503 (fitmodel not deployed yet) is shown
 * as a plain, expected message, not an error page - see
 * backend/api.py's get_tailoring_report docstring for why that's the
 * real, current state rather than a bug.
 */
export function TailoringReportPage() {
  const { id } = useParams<{ id: string }>();
  const { token, logout } = useAuth();
  const navigate = useNavigate();

  const [isLoading, setIsLoading] = useState(true);
  const [notAvailable, setNotAvailable] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [suggestions, setSuggestions] = useState<TailoringSuggestionOut[]>([]);

  useEffect(() => {
    if (!token || !id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchTailoringReport(token, id);
        if (cancelled) return;
        setTitle(data.title);
        setCompanyName(data.company_name);
        setSuggestions(data.suggestions);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        const message = err instanceof Error ? err.message : "Failed to load tailoring report.";
        if (message.toLowerCase().includes("not available yet")) {
          setNotAvailable(true);
        } else {
          setLoadError(message);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, id, logout]);

  function goBack() {
    navigate(-1);
  }

  const backLink = (
    <a
      href="/"
      className="back-link"
      onClick={(e) => {
        e.preventDefault();
        goBack();
      }}
    >
      ← Back
    </a>
  );

  if (isLoading) {
    return <p className="job-list-status">Loading… (first load can take a while - a real model is warming up)</p>;
  }

  if (loadError) {
    return (
      <div className="jobs-page">
        <p className="job-list-status job-list-error">{loadError}</p>
        <p className="auth-switch">{backLink}</p>
      </div>
    );
  }

  if (notAvailable) {
    return (
      <div className="jobs-page">
        <p className="tailoring-page-header">{backLink}</p>
        <p className="job-list-status">
          Tailoring reports aren't available yet - the model service isn't deployed. Check back once it is.
        </p>
      </div>
    );
  }

  return (
    <div className="jobs-page">
      <p className="tailoring-page-header">{backLink}</p>
      <h1 className="score-page-title">{title}</h1>
      <p className="job-company">{companyName}</p>

      {suggestions.length === 0 ? (
        <p className="job-list-status">No specific gaps found - your resume already covers this JD's distinctive Required-section terms.</p>
      ) : (
        <ul className="tailoring-suggestion-list">
          {suggestions.map((s, i) => (
            <li key={`${s.jd_term}-${i}`} className={`tailoring-suggestion tailoring-suggestion-${s.type}`}>
              <div className="tailoring-suggestion-header">
                <span className="tailoring-suggestion-term">{s.jd_term}</span>
                <span className="tailoring-suggestion-type-badge">{TYPE_LABELS[s.type]}</span>
              </div>
              <p className="tailoring-suggestion-message">{s.message}</p>
              {s.draft_bullet && (
                <div className="tailoring-suggestion-draft">
                  <span className="tailoring-suggestion-draft-label">Draft (edit before using):</span>
                  <p className="tailoring-suggestion-draft-text">{s.draft_bullet}</p>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
