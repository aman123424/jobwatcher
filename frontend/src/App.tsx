import "./App.css";
import { JobList } from "./components/JobList";
import { RefreshBar } from "./components/RefreshBar";
import { ViewToggle } from "./components/ViewToggle";
import { useJobsData } from "./hooks/useJobsData";

/**
 * Pure composition - every actual behavior (fetching, state, view
 * switching) lives in useJobsData; every actual rendering decision
 * (loading/error/empty states, one job's layout) lives in the
 * components below. This file's only job is wiring the two together,
 * which is what keeps it readable even as the app grows.
 */
function App() {
  const {
    view,
    setView,
    jobs,
    updatedAt,
    isLoadingView,
    isRefreshing,
    error,
    refresh,
  } = useJobsData();

  return (
    <div className="app">
      <header className="app-header">
        <h1>JobWatcher</h1>
        <p className="app-subtitle">
          Fresh Software Engineer postings, scored against your resume.
        </p>
      </header>

      <RefreshBar
        updatedAt={updatedAt}
        isRefreshing={isRefreshing}
        onRefresh={refresh}
      />
      <ViewToggle view={view} onChange={setView} />

      <main>
        <JobList
          jobs={jobs}
          isLoading={isLoadingView}
          error={error}
          hasEverRefreshed={updatedAt !== null}
        />
      </main>
    </div>
  );
}

export default App;
