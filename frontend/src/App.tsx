import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { SearchView } from './SearchView'
import { BuildView } from './BuildView'
import { EvalTable } from './EvalTable'
import { BenchmarksPage } from './BenchmarksPage'
import { HistoryView } from './HistoryView'
import { config } from './config'
import { useTheme } from './useTheme'
import { ServiceStatusBar, ServiceStatusProvider } from './ServiceStatus'
import { SettingsPanel } from './SettingsPanel'

/** The dashboard is now a tab of Benchmarks; old links keep their ?run=. */
function DashboardRedirect() {
  const params = new URLSearchParams(useLocation().search)
  params.set('tab', 'dashboard')
  return <Navigate to={`/benchmarks?${params.toString()}`} replace />
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  )
}

export function App() {
  const { theme, toggle } = useTheme()

  return (
    <ServiceStatusProvider>
      <div className="app">
        <header className="app-head">
          <div className="brand">
            <h1>Agentic GraphRAG</h1>
            <span className="muted">Three-pipeline comparison</span>
          </div>
          <nav>
            <NavLink to="/" end>
              Search
            </NavLink>
            <NavLink to="/build">Build</NavLink>
            <NavLink to="/benchmarks">Benchmarks</NavLink>
            <NavLink to="/eval">Eval table</NavLink>
            <NavLink to="/history">History</NavLink>
          </nav>
          <div className="head-right">
            {config.useMockApi && (
              <span className="mock-flag" title="VITE_USE_MOCK_API=true — every screen is served from src/fixtures">
                mock data
              </span>
            )}
            {!config.useMockApi && <ServiceStatusBar />}
            <SettingsPanel />
            <button
              type="button"
              className="theme-toggle"
              onClick={toggle}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<SearchView />} />
            <Route path="/build" element={<BuildView />} />
            <Route path="/dashboard" element={<DashboardRedirect />} />
            <Route path="/eval" element={<EvalTable />} />
            <Route path="/benchmarks" element={<BenchmarksPage />} />
            <Route path="/history" element={<HistoryView />} />
            <Route path="*" element={<p className="pad">Not found.</p>} />
          </Routes>
        </main>

        <footer className="app-foot">
          <span>
            Telemetry framework<strong>Standard RAG · GraphRAG · Agentic GraphRAG</strong>
          </span>
          <span>Deterministic Benchmark Cockpit</span>
        </footer>
      </div>
    </ServiceStatusProvider>
  )
}

