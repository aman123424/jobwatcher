import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export function HomePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="home-page">
      <header className="home-header">
        <h1>JobWatcher</h1>
        <button type="button" className="logout-button" onClick={handleLogout}>
          Log out
        </button>
      </header>

      <p className="home-greeting">Welcome, {user?.name}.</p>
      <p className="home-subtitle">
        Fresh Software Engineer postings from every company we track, scored against your resume.
      </p>

      <button type="button" className="get-started-button" onClick={() => navigate("/app")}>
        Get Started
      </button>
    </div>
  );
}
