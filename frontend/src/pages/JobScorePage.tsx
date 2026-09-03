import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import "./JobScorePage.scss";
import { fetchJobScore, saveJobScore, UnauthorizedError } from "../api/client";
import { useAuth } from "../hooks/useAuth";

/**
 * Admin-only (see App.tsx). Loads (and, on first visit, LAZILY
 * COMPUTES via scoring.py's score_job()) this admin's resume-fit
 * score for one job, and lets them overwrite it with their own -
 * typically pasted in after asking Claude directly, the same
 * bootstrap-and-correct workflow the seniority-level classifier will
 * eventually use too. Saving here always marks the row "reviewed"
 * (see JobScoreSource in backend/models.py) - that's the real,
 * trustworthy training signal for the eventual classifier, as
 * distinct from the unreviewed "auto" baseline this page starts with.
 */
export function JobScorePage() {
  const { id } = useParams<{ id: string }>();
  const { token, logout } = useAuth();
  const navigate = useNavigate();

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [link, setLink] = useState("");
  const [rawDescription, setRawDescription] = useState<string | null>(null);
  const [source, setSource] = useState<"auto" | "reviewed">("auto");
  const [score, setScore] = useState(0);
  const [reasoning, setReasoning] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchJobScore(token, id);
        if (cancelled) return;
        setTitle(data.title);
        setCompanyName(data.company_name);
        setLink(data.link);
        setRawDescription(data.raw_description);
        setSource(data.source);
        setScore(data.score);
        setReasoning(data.reasoning);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          logout();
          return;
        }
        setLoadError(err instanceof Error ? err.message : "Failed to load score.");
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
      const result = await saveJobScore(token, id, { score, reasoning });
      setSource(result.source);
      setSuccess("Saved.");
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to save score.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function goBack() {
    navigate(-1);
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
            href="/"
            onClick={(e) => {
              e.preventDefault();
              goBack();
            }}
          >
            ← Back
          </a>
        </p>
      </div>
    );
  }

  return (
    <div className="jobs-page">
      <div className="score-page-header">
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
        <span className={`score-source-badge${source === "reviewed" ? " score-source-badge-reviewed" : ""}`}>
          {source === "reviewed" ? "Reviewed" : "Auto (unreviewed)"}
        </span>
      </div>

      <h1 className="score-page-title">{title}</h1>
      <p className="job-company">
        {companyName} ·{" "}
        <a href={link} target="_blank" rel="noreferrer">
          View posting
        </a>
      </p>

      <div className="score-page-columns">
        <div className="score-page-jd">
          <h2>Job description</h2>
          <p className="score-page-jd-text">{rawDescription ?? "No description available."}</p>
        </div>

        <form className="score-page-form" onSubmit={handleSubmit}>
          <label>
            Score (0-100)
            <input
              type="number"
              min={0}
              max={100}
              value={score}
              onChange={(e) => setScore(Number(e.target.value))}
              required
            />
          </label>

          <label>
            Reasoning
            <textarea
              className="score-page-textarea"
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
              rows={16}
              required
            />
          </label>

          {error && <p className="auth-error">{error}</p>}
          {success && <p className="auth-success">{success}</p>}

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Save"}
          </button>
        </form>
      </div>
    </div>
  );
}
