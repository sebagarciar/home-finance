import { Suspense, lazy, useEffect, useState } from 'react'
import { Login } from './pages/Login'
import { PageLoading } from './components/PageLoading'

// Route-level code splitting: each tab is its own chunk, fetched on first
// visit. Recharts lands in a shared chunk pulled in with the first page that
// needs it (Dashboard, the default tab) instead of one monolithic bundle.
const Dashboard = lazy(() => import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const Portfolio = lazy(() => import('./pages/Portfolio').then((m) => ({ default: m.Portfolio })))
const Forecast = lazy(() => import('./pages/Forecast').then((m) => ({ default: m.Forecast })))
const Transactions = lazy(() => import('./pages/Transactions').then((m) => ({ default: m.Transactions })))
import { CurrencyProvider, useCurrency } from './lib/currency'
import { clearToken, getToken, registerUnauthorizedHandler } from './lib/auth'

type Tab = 'dashboard' | 'portfolio' | 'forecast' | 'transactions'

const TABS: Tab[] = ['dashboard', 'portfolio', 'forecast', 'transactions']

const TITLES: Record<Tab, string> = {
  dashboard: 'Overview',
  portfolio: 'Portfolio',
  forecast: 'Forecast',
  transactions: 'Transactions',
}
const SUBTITLES: Record<Tab, string> = {
  dashboard: 'Everything the household owns and spends, in one place',
  portfolio: 'Net worth, holdings, and historical balance',
  forecast: 'Monte Carlo net-worth projection with uncertainty bands',
  transactions: 'Every transaction across your accounts',
}

const ICONS: Record<Tab, React.ReactNode> = {
  dashboard: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />
    </svg>
  ),
  portfolio: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </svg>
  ),
  forecast: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12c4-7 14-7 18 0" />
      <path d="M3 17c4-5 14-5 18 0" />
      <path d="M3 7c4-9 14-9 18 0" />
    </svg>
  ),
  transactions: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  ),
}

function TopNav({ tab, setTab, onLogout }: { tab: Tab; setTab: (t: Tab) => void; onLogout: () => void }) {
  const { display, setDisplay, privacy, setPrivacy } = useCurrency()
  return (
    <header className="topnav">
      <div className="brand">
        <img className="brand-mark" src="/favicon.svg" alt="" />
        <span className="label">Home Finance</span>
      </div>
      <nav className="topnav-links">
        {TABS.map((t) => (
          <NavLink key={t} active={tab === t} onClick={() => setTab(t)} icon={ICONS[t]} label={TITLES[t]} />
        ))}
      </nav>
      <div className="topnav-tools">
        <div className="segmented">
          {(['CLP', 'EUR'] as const).map((c) => (
            <button key={c} className={display === c ? 'active' : ''} onClick={() => setDisplay(c)}>
              {c}
            </button>
          ))}
        </div>
        <button
          className={`icon-btn${privacy ? ' active' : ''}`}
          onClick={() => setPrivacy(!privacy)}
          title={privacy ? 'Show amounts' : 'Hide amounts'}
          aria-label={privacy ? 'Show amounts' : 'Hide amounts'}
        >
          {privacy ? (
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a19.6 19.6 0 0 1 5.06-5.94" />
              <path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a19.5 19.5 0 0 1-2.16 3.19" />
              <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
              <path d="M1 1l22 22" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
        <button className="icon-btn logout-link" onClick={onLogout} title="Sign out" aria-label="Sign out">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
        </button>
      </div>
    </header>
  )
}

function NavLink({
  active, onClick, icon, label,
}: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button className={`nav-link${active ? ' active' : ''}`} onClick={onClick} title={label}>
      <span className="icon">{icon}</span>
      <span className="label">{label}</span>
    </button>
  )
}

const TODAY = new Date().toLocaleDateString('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

function Header({ tab }: { tab: Tab }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{TITLES[tab]}</h1>
        <p className="page-subtitle">{SUBTITLES[tab]}</p>
      </div>
      <span className="header-date">{TODAY}</span>
    </div>
  )
}

export function App() {
  const [tab, setTab] = useState<Tab>('dashboard')
  const [authed, setAuthed] = useState(() => getToken() !== null)

  useEffect(() => {
    registerUnauthorizedHandler(() => setAuthed(false))
  }, [])

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />
  }

  function handleLogout() {
    clearToken()
    setAuthed(false)
  }

  return (
    <CurrencyProvider>
      <div className="app-shell">
        <TopNav tab={tab} setTab={setTab} onLogout={handleLogout} />
        <main className="main">
          <div className="content">
            <Header tab={tab} />
            <Suspense fallback={<PageLoading />}>
              {tab === 'dashboard' && <Dashboard />}
              {tab === 'portfolio' && <Portfolio />}
              {tab === 'forecast' && <Forecast />}
              {tab === 'transactions' && <Transactions />}
            </Suspense>
          </div>
        </main>
      </div>
    </CurrencyProvider>
  )
}

export default App
