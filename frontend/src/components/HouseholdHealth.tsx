// Household-health strip: spend-vs-usual, cash runway, and currency exposure.
// Reads the shared spending-summary + net-worth caches (no extra fetches).
import { useMemo } from 'react'
import { useSpendingSummary, useNetworthCurrent, useSpendingPace } from '../api/hooks'
import { useCurrency } from '../lib/currency'

const TRAILING_MONTHS = 6

type Metrics = {
  currentMonth: string | null
  currentSpend: number
  usualSpend: number | null
  avgMonthlySpend: number
}

// Stable colors for the common currencies; anything else hashes into the palette.
const CURRENCY_COLOR: Record<string, string> = {
  CLP: 'var(--cat-5)',
  EUR: 'var(--cat-2)',
  USD: 'var(--cat-6)',
  GBP: 'var(--cat-4)',
}
const PALETTE = ['var(--cat-1)', 'var(--cat-3)', 'var(--cat-7)', 'var(--cat-8)']
function currencyColor(code: string, i: number): string {
  return CURRENCY_COLOR[code] ?? PALETTE[i % PALETTE.length]
}

export function HouseholdHealth() {
  const summaryQ = useSpendingSummary()
  const networthQ = useNetworthCurrent()
  const todayDay = new Date().getDate()
  const paceQ = useSpendingPace(todayDay)
  const { format } = useCurrency()
  const summary = summaryQ.data
  const networth = networthQ.data

  const metrics = useMemo<Metrics | null>(() => {
    if (!summary) return null
    const spendByMonth = new Map(summary.by_month.map((m) => [m.month, Number(m.total)]))
    const months = [...spendByMonth.keys()].sort()
    if (months.length === 0) return null

    // "Spend vs usual": this month's spend against the average of the months
    // right before it — a behavioral "am I spending more than normal?" signal.
    // More meaningful than a savings rate when income is low/irregular.
    const currentMonth = months[months.length - 1]
    const currentSpend = spendByMonth.get(currentMonth) ?? 0
    const priorMonths = months.slice(-1 - TRAILING_MONTHS, -1)
    const usualSpend =
      priorMonths.length > 0
        ? priorMonths.reduce((s, m) => s + (spendByMonth.get(m) ?? 0), 0) / priorMonths.length
        : null
    // Runway uses real average monthly spend across all recent months,
    // including the current one — independent of the spend-vs-usual window.
    const recent = months.slice(-TRAILING_MONTHS)
    const recentSpend = recent.reduce((s, m) => s + (spendByMonth.get(m) ?? 0), 0)
    const avgMonthlySpend = recent.length > 0 ? recentSpend / recent.length : 0

    return { currentMonth, currentSpend, usualSpend, avgMonthlySpend }
  }, [summary])

  const runwayMonths = useMemo(() => {
    if (!networth || !metrics || metrics.avgMonthlySpend <= 0) return null
    const cash = Number(networth.cash_total_in_base)
    return cash / metrics.avgMonthlySpend
  }, [networth, metrics])

  const exposure = useMemo(() => {
    if (!networth) return []
    const positives = networth.by_currency
      .map((r) => ({ currency: r.currency, value: Number(r.total_in_base) }))
      .filter((r) => r.value > 0)
    const total = positives.reduce((s, r) => s + r.value, 0)
    if (total <= 0) return []
    return positives
      .map((r) => ({ ...r, share: r.value / total }))
      .sort((a, b) => b.share - a.share)
  }, [networth])

  const expectedByDay = paceQ.data?.expected_by_day != null
    ? Number(paceQ.data.expected_by_day)
    : null

  if (summaryQ.isLoading || networthQ.isLoading) return <HealthSkeleton />
  if (!metrics && exposure.length === 0) return null

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Household health</h2>
        <span className="card-meta">Spend vs usual · cash runway · currency exposure</span>
      </div>
      <div className="health-grid">
        <SpendingPace metrics={metrics} expectedByDay={expectedByDay} format={format} />
        <Runway months={runwayMonths} />
        <CurrencyExposure exposure={exposure} />
      </div>
    </div>
  )
}

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`
}

function SpendingPace({
  metrics,
  expectedByDay,
  format,
}: {
  metrics: Metrics | null
  expectedByDay: number | null   // actual avg spend from day 1→today across past months
  format: (n: number) => string
}) {
  if (!metrics || metrics.usualSpend === null || metrics.usualSpend <= 0) {
    return <Metric label="Month pace" value="—" sub="Not enough history yet" />
  }

  const today = new Date()
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
  const daysPct = today.getDate() / daysInMonth

  // Prefer historical partial-month average (captures lumpy day-1 payments like rent).
  // Fall back to linear interpolation only while the pace endpoint is loading.
  const expectedByNow = expectedByDay ?? metrics.usualSpend * daysPct
  const ratio = expectedByNow > 0 ? metrics.currentSpend / expectedByNow : 0

  // >5% over expected pace → red; >5% under → green; otherwise neutral.
  const tone = ratio > 1.05 ? 'neg' : ratio < 0.95 ? 'pos' : undefined
  const barColor =
    tone === 'neg' ? 'var(--negative-text)' : tone === 'pos' ? 'var(--positive-text)' : 'var(--text-muted)'

  const monthLabel = new Date(`${metrics.currentMonth}-01T00:00:00`).toLocaleString('en-US', {
    month: 'short',
  })

  const deltaLabel =
    tone === 'neg'
      ? `+${((ratio - 1) * 100).toFixed(0)}% over pace`
      : tone === 'pos'
        ? `${(((ratio - 1) * 100).toFixed(0))}% under pace`
        : 'On pace'

  return (
    <div className="health-metric">
      <div className="tile-label">Month pace · {monthLabel}</div>
      <div
        className="tile-value num"
        style={{
          color:
            tone === 'neg'
              ? 'var(--negative-text)'
              : tone === 'pos'
                ? 'var(--positive-text)'
                : 'var(--text-primary)',
        }}
      >
        {deltaLabel}
      </div>
      {/* Bar represents the full month; fill = spend so far; tick = today's position */}
      <div
        style={{
          position: 'relative',
          height: 6,
          borderRadius: 999,
          background: 'var(--surface-raised)',
          margin: '2px 0',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: '0 auto 0 0',
            width: `${Math.min((metrics.currentSpend / metrics.usualSpend) * 100, 100)}%`,
            borderRadius: 999,
            background: barColor,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: `${daysPct * 100}%`,
            top: -3,
            bottom: -3,
            width: 2,
            background: 'var(--text-faint)',
            borderRadius: 1,
            transform: 'translateX(-50%)',
          }}
        />
      </div>
      <div className="health-sub">
        Spent {format(metrics.currentSpend)} · usual by day {today.getDate()}: {format(expectedByNow)}
      </div>
    </div>
  )
}

function Runway({ months }: { months: number | null }) {
  if (months === null) {
    return <Metric label="Cash runway" value="—" sub="Set account balances + import spend" />
  }
  // Emergency-fund rule of thumb: ≥6 months comfortable, 3–6 thin, <3 tight.
  const tone = months >= 6 ? 'pos' : months >= 3 ? 'warn' : 'neg'
  return (
    <Metric
      label="Cash runway"
      value={`${months.toFixed(1)} mo`}
      tone={tone}
      sub="Net cash ÷ avg monthly spend"
    />
  )
}

function CurrencyExposure({ exposure }: { exposure: { currency: string; share: number }[] }) {
  if (exposure.length === 0) {
    return <Metric label="Currency exposure" value="—" sub="Add accounts or holdings" />
  }
  return (
    <div className="health-metric">
      <div className="tile-label">Currency exposure</div>
      <div className="exposure-bar">
        {exposure.map((e, i) => (
          <div
            key={e.currency}
            style={{ width: `${e.share * 100}%`, background: currencyColor(e.currency, i) }}
            title={`${e.currency} ${pct(e.share)}`}
          />
        ))}
      </div>
      <div className="exposure-legend">
        {exposure.map((e, i) => (
          <span key={e.currency} className="exposure-chip">
            <span className="dot" style={{ background: currencyColor(e.currency, i) }} />
            {e.currency} {pct(e.share)}
          </span>
        ))}
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'pos' | 'neg' | 'warn'
}) {
  const color =
    tone === 'pos'
      ? 'var(--positive-text)'
      : tone === 'neg'
        ? 'var(--negative-text)'
        : tone === 'warn'
          ? 'var(--pending-text)'
          : 'var(--text-primary)'
  return (
    <div className="health-metric">
      <div className="tile-label">{label}</div>
      <div className="tile-value num" style={{ color }}>
        {value}
      </div>
      {sub && <div className="health-sub">{sub}</div>}
    </div>
  )
}

function HealthSkeleton() {
  return (
    <div className="card">
      <div className="skel" style={{ height: 18, width: 160, marginBottom: 16 }} />
      <div className="health-grid">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skel" style={{ height: 64 }} />
        ))}
      </div>
    </div>
  )
}
