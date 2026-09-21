import { NavLink, Route, Routes } from 'react-router-dom'
import { SearchView } from './SearchView'
import { BuildView } from './BuildView'
import { Dashboard } from './Dashboard'
import { EvalTable } from './EvalTable'
import { config } from './config'

export function App() {
  return (
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
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/eval">Eval table</NavLink>
        </nav>
        {config.useMockApi && (
          <span className="mock-flag" title="VITE_USE_MOCK_API=true — every screen is served from src/fixtures">
            mock data
          </span>
        )}
      </header>

      <main>
        <Routes>
          <Route path="/" element={<SearchView />} />
          <Route path="/build" element={<BuildView />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/eval" element={<EvalTable />} />
          <Route path="*" element={<p className="pad">Not found.</p>} />
        </Routes>
      </main>
    </div>
  )
}
