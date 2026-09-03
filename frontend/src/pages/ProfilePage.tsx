import { useNavigate } from "react-router-dom";
import "../components/AppHeader.scss"; // reuses AppHeader's own header classes for this page's back-button header, without rendering the AppHeader component itself
import "./ProfilePage.scss";
import { useAuth } from "../hooks/useAuth";

/**
 * What the header's avatar menu's "View Profile" item (see AvatarMenu.tsx) links to.
 * Deliberately minimal - just this account's own details - not a
 * request to build out resume upload / skills / settings management
 * here; those stay separate, not-yet-built work of their own.
 */
export function ProfilePage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="jobs-page">
      <header className="jobs-page-header">
        <button type="button" className="back-link" onClick={() => navigate("/")}>
          ← Back
        </button>
        <h1>Profile</h1>
      </header>

      <dl className="profile-details">
        <dt>Name</dt>
        <dd>{user?.name}</dd>
        <dt>Email</dt>
        <dd>{user?.email}</dd>
        <dt>Plan</dt>
        <dd>{user?.tier === "paid" ? "Paid" : "Free"}</dd>
      </dl>
    </div>
  );
}
