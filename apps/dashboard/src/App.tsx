import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { OverviewPage } from '@/pages/dashboard/overview';
import { QualityPage } from '@/pages/dashboard/quality';
import { TracesPage } from '@/pages/dashboard/traces';
import { LivePage } from '@/pages/dashboard/live';
import { KgPage } from '@/pages/dashboard/kg';
import { InsightsPage } from '@/pages/dashboard/insights';
import { SystemPage } from '@/pages/dashboard/system';
import { ObservabilityPage } from '@/pages/dashboard/observability';
import { AlertsPage } from '@/pages/dashboard/alerts';
import { AlertsBadge } from '@/components/AlertsBadge';

const STORAGE_THEME = 'openclaw-dashboard-theme';

const nav = [
  { to: '/dashboard/overview', label: 'Overview' },
  { to: '/dashboard/quality', label: 'Quality' },
  { to: '/dashboard/traces', label: 'Traces' },
  { to: '/dashboard/live', label: 'Live' },
  { to: '/dashboard/kg', label: 'Knowledge Graph' },
  { to: '/dashboard/insights', label: 'Insights' },
  { to: '/dashboard/alerts', label: 'Alerts', badge: true },
  { to: '/dashboard/system', label: 'System' },
  { to: '/dashboard/observability', label: 'Observability' },
];

function App() {
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem(STORAGE_THEME);
    if (stored === 'light' || stored === 'dark') return stored === 'dark';
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true;
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add('dark');
      root.removeAttribute('data-theme');
    } else {
      root.classList.remove('dark');
      root.setAttribute('data-theme', 'light');
    }
    localStorage.setItem(STORAGE_THEME, dark ? 'dark' : 'light');
  }, [dark]);

  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-[var(--background)]">
        <nav className="border-b border-slate-700 bg-slate-800/90 backdrop-blur-sm sticky top-0 z-10 transition-colors duration-200">
          <div className="mx-auto max-w-6xl px-3 sm:px-4 flex items-center gap-0.5 overflow-x-auto overflow-y-hidden scrollbar-thin scrollbar-thumb-slate-600 scrollbar-track-transparent md:overflow-x-visible md:flex-wrap md:flex-nowrap">
            <NavLink
              to="/"
              end
              className="shrink-0 py-3 px-2 text-slate-400 hover:text-slate-200 text-sm font-medium transition-colors duration-200 touch-target flex items-center"
            >
              OpenClaw
            </NavLink>
            {nav.map(({ to, label, badge }) => (
              <div key={to} className="shrink-0 flex items-center gap-1">
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    `py-3 px-3 text-sm font-medium rounded-t transition-all duration-200 touch-target flex items-center ${
                      isActive ? 'text-sky-400 bg-slate-800 border-b-2 border-sky-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                    }`
                  }
                >
                  {label}
                </NavLink>
                {badge && <AlertsBadge />}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setDark((d) => !d)}
              className="shrink-0 p-2.5 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors duration-200 touch-target"
              title={dark ? 'Switch to light' : 'Switch to dark'}
              aria-label={dark ? 'Light mode' : 'Dark mode'}
            >
              {dark ? (
                <span aria-hidden>☀️</span>
              ) : (
                <span aria-hidden>🌙</span>
              )}
            </button>
          </div>
        </nav>
        <main className="flex-1 mx-auto w-full max-w-6xl p-4 md:p-6 animate-fade-in">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/dashboard/overview" element={<OverviewPage />} />
            <Route path="/dashboard/quality" element={<QualityPage />} />
            <Route path="/dashboard/traces" element={<TracesPage />} />
            <Route path="/dashboard/live" element={<LivePage />} />
            <Route path="/dashboard/kg" element={<KgPage />} />
            <Route path="/dashboard/insights" element={<InsightsPage />} />
            <Route path="/dashboard/system" element={<SystemPage />} />
            <Route path="/dashboard/observability" element={<ObservabilityPage />} />
            <Route path="/dashboard/alerts" element={<AlertsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
