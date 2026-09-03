import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

interface ProtectedRouteProps {
  children: ReactNode;
  /** Also requires the logged-in user to be an admin (see /add-company in App.tsx) - redirects to "/" rather than "/login", since the real problem here is a permission, not a missing session. This is a convenience redirect only: the actual access control is POST /companies' own get_current_admin check on the backend - a non-admin who somehow lands on the page still can't submit the form. */
  adminOnly?: boolean;
}

/**
 * Wraps a page that requires login (Home, and later the real jobs
 * pages) - redirects to /login if there's no logged-in user, rather
 * than rendering a page that would just fail on its first API call.
 */
export function ProtectedRoute({ children, adminOnly }: ProtectedRouteProps) {
  const { token, user } = useAuth();
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  if (adminOnly && !user?.is_admin) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
