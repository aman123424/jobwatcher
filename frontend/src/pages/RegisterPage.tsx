import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

/**
 * No resume upload here, deliberately - see the conversation this was
 * decided in: registration stays lightweight (name/email/password
 * only) for every new user, since resume upload is a paid-tier-only
 * concern that should be asked for later, contextually, when a user
 * actually engages with that feature - not upfront for everyone,
 * most of whom may stay on the free tier and never need it at all.
 */
export function RegisterPage() {
  const { register, isLoading, error } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      await register({ name, email, password });
      navigate("/");
    } catch {
      // Error is already captured in useAuth()'s `error` state and
      // rendered below - nothing further to do here.
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Create your account</h1>
        <p className="auth-subtitle">Fresh Software Engineer postings, scored against your resume.</p>

        <label>
          Name
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoComplete="name"
          />
        </label>

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>

        {error && <p className="auth-error">{error}</p>}

        <button type="submit" disabled={isLoading}>
          {isLoading ? "Creating account…" : "Create account"}
        </button>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  );
}
