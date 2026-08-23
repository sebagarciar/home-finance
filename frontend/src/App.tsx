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
import { useSpendingSummary } from './api/hooks'
import { clearToken, getToken, registerUnauthorizedHandler } from './lib/auth'

type Tab = 'dashboard' | 'portfolio' | 'forecast' | 'transactions'

function Sidebar({ tab, setTab, onLogout }: { tab: Tab; setTab: (t: Tab) => void; onLogout: () => void }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="logo">$</span>
        <span className="label">Home Finance</span>
      </div>
      <NavLink
        active={tab === 'dashboard'}
        onClick={() => setTab('dashboard')}
        icon={
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" />
          </svg>
        }
        label="Dashboard"
      />
      <NavLink
        active={tab === 'portfolio'}
        onClick={() => setTab('portfolio')}
        icon={
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M3 17l6-6 4 4 7-7" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M14 8h6v6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        }
        label="Portfolio"
      />
      <NavLink
        active={tab === 'forecast'}
        onClick={() => setTab('forecast')}
        icon={
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 12c4-7 14-7 18 0" />
            <path d="M3 17c4-5 14-5 18 0" />
            <path d="M3 7c4-9 14-9 18 0" />
          </svg>
        }
        label="Forecast"
      />
      <NavLink
        active={tab === 'transactions'}
        onClick={() => setTab('transactions')}
        icon={
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />
          </svg>
        }
        label="Transactions"
      />
      <div className="sidebar-spacer" />
      <button className="nav-link logout-link" onClick={onLogout} title="Sign out">
        <span className="icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
        </span>
        <span className="label">Sign out</span>
      </button>
    </aside>
  )
}

function NavLink({
  active, onClick, icon, label,
}: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button className={`nav-link${active ? ' active' : ''}`} onClick={onClick}>
      <span className="icon">{icon}</span>
      <span className="label">{label}</span>
    </button>
  )
}

function SummaryBar() {
  const { format } = useCurrency()
  const { data: summary, isError } = useSpendingSummary()

  const stats = (() => {
    if (!summary) return { spend: 0, income: 0, net: 0, latestMonth: '' }
    const months = [...summary.by_month].sort((a, b) => a.month.localeCompare(b.month))
    const latest = months[months.length - 1]
    const incomeMap = Object.fromEntries(summary.by_month_income.map((r) => [r.month, Number(r.total)]))
    const latestMonth = latest?.month ?? ''
    const spend = latest ? Number(latest.total) : 0
    const income = latestMonth ? (incomeMap[latestMonth] ?? 0) : 0
    return { spend, income, net: income - spend, latestMonth }
  })()

  const monthLabel = stats.latestMonth
    ? new Date(`${stats.latestMonth}-01T00:00:00`).toLocaleString('en-US', { month: 'long' })
    : '—'

  return (
    <div className="summary-bar">
      <Stat
        label={isError ? 'Income (offline)' : `${monthLabel} Income`}
        value={summary ? format(stats.income) : '—'}
        tone="pos"
      />
      <Stat
        label={isError ? 'Spend (offline)' : `${monthLabel} Spend`}
        value={summary ? format(stats.spend) : '—'}
        tone="neg"
      />
      <Stat
        label={isError ? 'Net (offline)' : `${monthLabel} Net`}
        value={summary ? format(stats.net) : '—'}
        tone={stats.net >= 0 ? 'pos' : 'neg'}
      />
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'pos' | 'neg' }) {
  return (
    <div className="summary-cell">
      <div className="summary-label">{label}</div>
      <div className="summary-value num">
        {value}
        {tone && value !== '—' && (
          <span className={`trend-pill ${tone}`}>{tone === 'pos' ? '↑' : '↓'}</span>
        )}
      </div>
    </div>
  )
}

const TITLES: Record<Tab, string> = {
  dashboard: 'Overview',
  portfolio: 'Portfolio',
  forecast: 'Forecast',
  transactions: 'Transactions',
}
const SUBTITLES: Record<Tab, string> = {
  dashboard: 'Income, spending, and category breakdown',
  portfolio: 'Net worth, holdings, and historical balance',
  forecast: 'Monte Carlo net-worth projection with uncertainty bands',
  transactions: 'Every transaction across your accounts',
}

const TODAY = new Date().toLocaleDateString('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

function Header({ tab }: { tab: Tab }) {
  const { display, setDisplay, privacy, setPrivacy } = useCurrency()
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{TITLES[tab]}</h1>
        <p className="page-subtitle">{SUBTITLES[tab]}</p>
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span className="header-date">{TODAY}</span>
        <button
          className={`privacy-toggle${privacy ? ' active' : ''}`}
          onClick={() => setPrivacy(!privacy)}
          title={privacy ? 'Show amounts' : 'Hide amounts'}
          aria-label={privacy ? 'Show amounts' : 'Hide amounts'}
        >
          {privacy ? (
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a19.6 19.6 0 0 1 5.06-5.94" />
              <path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a19.5 19.5 0 0 1-2.16 3.19" />
              <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
              <path d="M1 1l22 22" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
        <div className="segmented">
          {(['CLP', 'EUR'] as const).map((c) => (
            <button
              key={c}
              className={display === c ? 'active' : ''}
              onClick={() => setDisplay(c)}
            >
              {c}
            </button>
          ))}
        </div>
      </div>
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
        <Sidebar tab={tab} setTab={setTab} onLogout={handleLogout} />
        <main className="main">
          <SummaryBar />
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
