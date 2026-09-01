import { createContext, useContext, useState, type ReactNode } from "react";
import * as api from "../api/client";
import type { AuthUser, LoginPayload, RegisterPayload } from "../api/types";

const TOKEN_STORAGE_KEY = "jobwatcher_token";
const USER_STORAGE_KEY = "jobwatcher_user";

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Reads whatever was saved from a previous session, if any -
 * localStorage persists across page reloads/browser restarts, unlike
 * plain React state, which is why login state survives a refresh
 * instead of forcing a fresh login every time the page loads.
 * Wrapped in try/catch: a private-browsing tab or blocked site data
 * can make localStorage throw on access, not just return empty - this
 * treats that the same as "nobody's logged in" rather than crashing
 * the whole app on load.
 */
function loadStoredSession(): { token: string | null; user: AuthUser | null } {
  try {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    const rawUser = localStorage.getItem(USER_STORAGE_KEY);
    return { token, user: rawUser ? (JSON.parse(rawUser) as AuthUser) : null };
  } catch {
    return { token: null, user: null };
  }
}

function saveSession(token: string, user: AuthUser): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Same reasoning as loadStoredSession() above - if storage isn't
    // available, the user just won't stay logged in across a reload,
    // which is a degraded experience, not a crash.
  }
}

function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(USER_STORAGE_KEY);
  } catch {
    // Nothing meaningful to do if storage itself is unavailable.
  }
}

/**
 * Wraps the whole app (see App.tsx) so any component can find out
 * "who's logged in" via useAuth() below, without threading user/token
 * props down through every layer by hand.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const stored = loadStoredSession();
  const [user, setUser] = useState<AuthUser | null>(stored.user);
  const [token, setToken] = useState<string | null>(stored.token);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function login(payload: LoginPayload) {
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.login(payload);
      const { access_token, ...authUser } = response;
      saveSession(access_token, authUser);
      setToken(access_token);
      setUser(authUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
      throw err;
    } finally {
      setIsLoading(false);
    }
  }

  async function register(payload: RegisterPayload) {
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.register(payload);
      const { access_token, ...authUser } = response;
      saveSession(access_token, authUser);
      setToken(access_token);
      setUser(authUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
      throw err;
    } finally {
      setIsLoading(false);
    }
  }

  function logout() {
    clearSession();
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, token, isLoading, error, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// oxlint flags exporting both AuthProvider (a component) and useAuth
// (a hook) from one file as a Fast-Refresh hazard - real for a file
// that's actively being hot-reloaded during active edits, but this is
// the standard, common React context+hook pairing pattern, and
// splitting it into two files purely to satisfy dev-server tooling
// would be unnecessary indirection for a file this small.
// oxlint-disable-next-line react/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() must be used inside <AuthProvider>");
  }
  return ctx;
}
