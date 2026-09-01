import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

/**
 * Wraps a page that requires login (Home, and later the real jobs
 * pages) - redirects to /login if there's no logged-in user, rather
 * than rendering a page that would just fail on its first API call.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
