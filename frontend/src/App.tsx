import "./App.css";
import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthProvider } from "./hooks/useAuth";
import { ThemeProvider } from "./hooks/useTheme";
import { AddCompanyPage } from "./pages/AddCompanyPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { EditCompanyPage } from "./pages/EditCompanyPage";
import { JobsPage } from "./pages/JobsPage";
import { LoginPage } from "./pages/LoginPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RegisterPage } from "./pages/RegisterPage";

/**
 * Pure composition, same principle the old single-page version of
 * this file followed - AuthProvider owns login state, each page owns
 * its own rendering, this file just wires routes to pages.
 *
 * "/" IS the jobs page directly (merged 2026-09-02 - no separate Home
 * + "Get Started" click-through step anymore).
 */
function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <JobsPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/profile"
              element={
                <ProtectedRoute>
                  <ProfilePage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/companies"
              element={
                <ProtectedRoute adminOnly>
                  <CompaniesPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/add-company"
              element={
                <ProtectedRoute adminOnly>
                  <AddCompanyPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/companies/:id/edit"
              element={
                <ProtectedRoute adminOnly>
                  <EditCompanyPage />
                </ProtectedRoute>
              }
            />
            {/* Anything unrecognized falls back to home (which itself redirects to /login if not authenticated). */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
