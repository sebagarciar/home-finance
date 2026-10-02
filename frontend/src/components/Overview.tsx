// Consolidated household home: net worth by asset class (never per bank),
// this month's spending by category, the total, and recent activity.
// Reads the shared net-worth / spending / transaction caches.
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  useNetworthCurrent, useNetworthHistory, useSpendingPace, useSpendingSummary, useTransactions,
} from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { categoryStyle, categoryColorHex } from '../design/categories'

const TOP_CATEGORIES = 4
const TRAILING_MONTHS = 6

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {d}
  </svg>
)
const ICON = {
  cash: icon(<><path d="M3 7a2 2 0 0 1 2-2h13v4" /><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M16 13.5h2" /></>),
  invest: icon(<><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>),
  debt: icon(<><path d="M4 11 12 4l8 7v9H4z" /><path d="M10 20v-5h4v5" /></>),
  spend: icon(<><path d="M3 4h2l2 11h11l2-7H7" /><circle cx="9" cy="19" r="1.5" /><circle cx="17" cy="19" r="1.5" /></>),
  info: icon(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>),
  in: icon(<><rect x="3" y="6" width="18" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /></>),
}

const CLASS_LABEL: Record<string, string> = {
  equity: 'Equity', bonds: 'Bonds', bond: 'Bonds', crypto: 'Crypto', fund: 'Funds',
  real_estate: 'Real estate', commodity: 'Commodities', cash: 'Cash',
}

export function Overview() {
  const { format, privacy, display } = useCurrency()
  const networthQ = useNetworthCurrent()
  const historyQ = useNetworthHistory()
  const summaryQ = useSpendingSummary()
  const recentQ = useTransactions({ limit: 5 })
  const paceQ = useSpendingPace(new Date().getDate())
  const nw = networthQ.data
  const summary = summaryQ.data

  const classes = useMemo(() => {
    if (!nw) return null
    const byClass = new Map(nw.by_asset_class.map((r) => [r.asset_class, Number(r.total_in_base)]))
    const cash = byClass.get('cash') ?? 0
    const debt = byClass.get('debt') ?? 0 // already negative
    const invest = Number(nw.holdings_total_in_base)
    const cashCurrencies = [
      ...new Set(
        nw.by_account
          .filter((a) => a.type !== 'debt' && Number(a.cash_native) !== 0)
          .map((a) => a.native_currency),
      ),
    ]
    const investClasses = [...byClass.entries()]
      .filter(([k, v]) => k !== 'cash' && k !== 'debt' && v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k]) => CLASS_LABEL[k] ?? k)
    const assets = cash + invest
    return { cash, debt, invest, cashCurrencies, investClasses, assets }
  }, [nw])

  const total = nw ? Number(nw.total_in_base) : null

  // Change since the first snapshot of the current year (or the earliest one).
  const change = useMemo(() => {
    // Skip empty snapshots (taken before any balances were entered).
    const pts = historyQ.data?.filter((p) => Number(p.total_in_base) !== 0)
    if (!pts?.length || total == null) return null
    const year = String(new Date().getFullYear())
    const start = pts.find((p) => p.date.startsWith(year)) ?? pts[0]
    const label = start.date.startsWith(year)
      ? 'this year'
      : `since ${new Date(`${start.date}T00:00:00`).toLocaleString('en-US', { month: 'short', year: 'numeric' })}`
    return { delta: total - Number(start.total_in_base), label }
  }, [historyQ.data, total])

  const month = useMemo(() => {
    if (!summary) return null
    const months = [...new Set(summary.by_month.map((m) => m.month))].sort()
    const current = months[months.length - 1]
    if (!current) return null
    const cats = summary.by_month_category
      .filter((r) => r.month === current)
      .map((r) => ({ category: r.category, total: Number(r.total) }))
      .filter((r) => r.total > 0)
      .sort((a, b) => b.total - a.total)
    const spend = cats.reduce((s, c) => s + c.total, 0)
    const top = cats.slice(0, TOP_CATEGORIES)
    const rest = cats.slice(TOP_CATEGORIES).reduce((s, c) => s + c.total, 0)
    const rows = rest > 0 ? [...top, { category: 'Other', total: rest }] : top
    // "Usual" for the running month is what the trailing months had spent by
    // this day (spending pace), so a month a few days old isn't compared to
    // full months. A past month compares against the trailing full-month mean.
    const isRunning = current === new Date().toISOString().slice(0, 7)
    const spendByMonth = new Map(summary.by_month.map((m) => [m.month, Number(m.total)]))
    const prior = months.slice(-1 - TRAILING_MONTHS, -1)
    const usual = isRunning
      ? (paceQ.data?.expected_by_day != null ? Number(paceQ.data.expected_by_day) : null)
      : prior.length
        ? prior.reduce((s, m) => s + (spendByMonth.get(m) ?? 0), 0) / prior.length
        : null
    const vsUsual = usual && usual > 0 ? (spend - usual) / usual : null
    const label = new Date(`${current}-01T00:00:00`).toLocaleString('en-US', { month: 'long' })
    return { label, spend, rows, vsUsual }
  }, [summary, paceQ.data])

  const pct = (x: number) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(Math.round(x * 100))}%`
  const signed = (x: number) => (x > 0 ? `+${format(x)}` : x < 0 ? `−${format(-x)}` : format(0))

  return (
    <div className="overview">
      <div className="overview-col">
        <h2 className="section-title">Net worth by type</h2>
        <div className="class-grid">
          {classes ? (
            <>
              <ClassCard icon={ICON.cash} title="Cash" sub={classes.cashCurrencies.join(' · ') || 'No balances yet'} amount={format(classes.cash)} />
              <ClassCard icon={ICON.invest} title="Investments" sub={classes.investClasses.join(' · ') || 'No holdings yet'} amount={format(classes.invest)} />
              <ClassCard
                icon={ICON.debt}
                title="Debt"
                sub={classes.debt < 0 && classes.assets > 0 ? `${Math.round((-classes.debt / classes.assets) * 100)}% of assets` : 'No debt'}
                amount={classes.debt < 0 ? `−${format(-classes.debt)}` : format(0)}
              />
              <ClassCard
                soft
                icon={ICON.spend}
                title={month ? `Spent in ${month.label}` : 'Spending'}
                sub={month?.vsUsual != null ? `${pct(month.vsUsual)} vs usual` : 'No history yet'}
                amount={month ? format(month.spend) : '—'}
              />
            </>
          ) : (
            [0, 1, 2, 3].map((i) => <div key={i} className="skel" style={{ height: 108, borderRadius: 16 }} />)
          )}
        </div>

        {month && month.rows.length > 0 && (
          <>
            <h2 className="section-title" style={{ marginTop: 20 }}>Spending in {month.label}</h2>
            <div className="panel">
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
                <p className="panel-amount lg num">{format(month.spend)}</p>
                {month.vsUsual != null && !privacy && (
                  // Spending less than usual is the good direction.
                  <span className={`trend-pill ${month.vsUsual <= 0 ? 'pos' : 'neg'}`}>{pct(month.vsUsual)} vs usual</span>
                )}
              </div>
              <div className="catbar">
                {month.rows.map((r) => (
                  <span key={r.category} style={{ flex: r.total, background: categoryColorHex(r.category) }} />
                ))}
              </div>
              <div className="cat-legend">
                {month.rows.map((r) => (
                  <div key={r.category} className="cat-legend-row">
                    <i style={{ background: categoryColorHex(r.category) }} />
                    <span>{categoryStyle(r.category).label}</span>
                    <span className="amt num">{format(r.total)}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      <div className="overview-col">
        <h2 className="section-title">
          Total
          <InfoTip label="How the total is calculated">
            Cash balances plus holdings valued at today&rsquo;s prices and FX, minus debt.
            Shown in {display}.
          </InfoTip>
        </h2>
        <div className="panel">
          {total == null ? (
            <div className="skel" style={{ height: 42, width: 220 }} />
          ) : (
            <p className="panel-amount num">{format(total)}</p>
          )}
          {change && !privacy && (
            <p style={{ margin: '10px 0 0' }}>
              <span className={`trend-pill ${change.delta >= 0 ? 'pos' : 'neg'}`}>
                {signed(change.delta)} {change.label}
              </span>
            </p>
          )}
          {classes && (
            <dl className="panel-rows">
              <div className="panel-row"><dt>Assets</dt><dd className="num">{format(classes.assets)}</dd></div>
              <div className="panel-row"><dt>Debt</dt><dd className="num">{classes.debt < 0 ? `−${format(-classes.debt)}` : format(0)}</dd></div>
            </dl>
          )}
        </div>

        <h2 className="section-title" style={{ marginTop: 20 }}>Recent activity</h2>
        <div className="activity">
          {recentQ.data && recentQ.data.length > 0 ? (
            recentQ.data.slice(0, 5).map((t) => {
              const amt = Number(t.amount_in_base)
              const cat = categoryStyle(t.category)
              return (
                <div key={t.id} className="activity-item">
                  <span className="disc sm">{amt > 0 ? ICON.in : ICON.spend}</span>
                  <div className="activity-main">
                    <div className="activity-title">{t.normalized_description || t.raw_description}</div>
                    <div className="activity-meta">
                      {cat.label} · {new Date(`${t.date}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </div>
                  </div>
                  <span className={`activity-amt num${amt > 0 ? ' pos' : ''}`}>{signed(amt)}</span>
                </div>
              )
            })
          ) : (
            <div className="activity-empty">{recentQ.isLoading ? 'Loading…' : 'No recent transactions'}</div>
          )}
        </div>
      </div>
    </div>
  )
}

function ClassCard({
  icon, title, sub, amount, soft,
}: { icon: ReactNode; title: string; sub: string; amount: string; soft?: boolean }) {
  return (
    <div className={`class-card${soft ? ' soft' : ''}`}>
      <span className="disc">{icon}</span>
      <div className="class-card-body">
        <div className="class-card-title">{title}</div>
        <div className="class-card-sub">{sub}</div>
      </div>
      <span className="class-card-amount num">{amount}</span>
    </div>
  )
}

// Info icon with an explanation bubble: opens on hover, keyboard focus, or tap;
// closes on leave, blur, an outside tap, or Escape.
function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span
      ref={ref}
      className="infotip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="infotip-btn"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {ICON.info}
      </button>
      {open && (
        <span id={id} role="tooltip" className="infotip-bubble">
          {children}
        </span>
      )}
    </span>
  )
}
