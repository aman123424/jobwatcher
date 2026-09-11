import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import * as api from "../api/client";
import type { AuthResponse, AuthUser, LoginPayload, RegisterPayload } from "../api/types";

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  /**
   * True only during the ONE silent /auth/refresh attempt on app load
   * (see the bootstrap effect below) - distinct from `isLoading`,
   * which covers an explicit login()/register() submission. Exists so
   * ProtectedRoute.tsx can tell "we don't know yet if there's a valid
   * session" apart from "we checked, and there genuinely isn't one" -
   * without it, a page reload would flash straight to /login before
   * the refresh cookie even got a chance to prove a session still
   * exists.
   */
  isBootstrapping: boolean;
  isLoading: boolean;
  error: string | null;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function toAuthUser({ access_token: _access_token, token_type: _token_type, ...user }: AuthResponse): AuthUser {
  return user;
}

/**
 * Wraps the whole app (see App.tsx) so any component can find out
 * "who's logged in" via useAuth() below, without threading user/token
 * props down through every layer by hand.
 *
 * ACCESS TOKEN LIVES IN MEMORY ONLY (changed 2026-09-10, alongside the
 * refresh-token flow) - deliberately NOT persisted to localStorage
 * anymore, unlike the single-JWT design this replaced. That's the
 * actual security property the refresh-token split buys: nothing
 * readable by an XSS payload survives a page reload. The tradeoff is
 * exactly what the bootstrap effect below exists to hide - `token`
 * starts null on every fresh mount, even for someone who never logged
 * out, so the app can't render anything authenticated until that
 * effect either succeeds (a valid HttpOnly refresh cookie was still
 * there) or fails (genuinely logged out / session expired).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Registers with client.ts's request() (see setSessionRefreshedHandler's
  // own docstring) so a SILENT background refresh - triggered mid-
  // session when an access token expires while the app is already in
  // use, not just this effect's own explicit call below - still
  // updates this state. Otherwise the fetch layer would keep working
  // fine off its own freshly-rotated token while React kept rendering
  // the stale, already-expired one until the next full page load.
  useEffect(() => {
    api.setSessionRefreshedHandler((auth) => {
      setToken(auth.access_token);
      setUser(toAuthUser(auth));
    });
    return () => api.setSessionRefreshedHandler(null);
  }, []);

  // The one thing that makes memory-only tokens survive a reload: on
  // every fresh mount, try to silently trade the HttpOnly refresh
  // cookie (if the browser still has one) for a new access token,
  // before rendering anything that assumes a session either way.
  // Runs once - login()/register() below already set fresh state
  // themselves, so there's nothing for a mount-time effect to redo
  // right after either of those.
  useEffect(() => {
    let cancelled = false;
    // tryRefreshSession(), NOT api.refreshSession() directly - shares
    // the same in-flight guard client.ts's automatic 401-retry uses
    // (see that function's own docstring). Without it, React 18
    // StrictMode's development-only double-invoke of this effect would
    // fire two real /auth/refresh requests carrying the same
    // not-yet-rotated cookie value, racing each other. Already resolves
    // to null (never throws) on failure, and already calls the handler
    // registered above on success - this effect only needs to track
    // isBootstrapping itself.
    api
      .tryRefreshSession()
      .finally(() => {
        if (!cancelled) setIsBootstrapping(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(payload: LoginPayload) {
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.login(payload);
      setToken(response.access_token);
      setUser(toAuthUser(response));
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
      setToken(response.access_token);
      setUser(toAuthUser(response));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
      throw err;
    } finally {
      setIsLoading(false);
    }
  }

  function logout() {
    // Best-effort - fired and not awaited: the user should end up
    // logged out in THIS browser immediately regardless of whether the
    // revoke-on-the-server call itself succeeds (a network blip
    // shouldn't strand someone in a "still looks logged in" UI). The
    // cookie is HttpOnly, so there's nothing for the frontend to clear
    // client-side anyway - only the server can actually revoke/clear it.
    api.logoutSession().catch(() => {});
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, token, isBootstrapping, isLoading, error, login, register, logout }}>
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
