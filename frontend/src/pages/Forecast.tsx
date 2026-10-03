import { useMemo, useState } from 'react'
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceDot,
} from 'recharts'
import type { ForecastBand, ForecastResult } from '../api/client'
import { useForecast } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { chart } from '../design/chartTheme'
import { useNav } from '../lib/nav'
import { Profile } from './Profile'
import { Goals } from '../components/Goals'
import { probColor } from '../lib/goals'

const HORIZONS = [5, 10, 20, 30]
const SEED = 42
const N_PATHS = 5000

// Net-worth green, matching the Portfolio history chart. Bands fade from the
// median outward; cobalt accent is reserved for CTAs, never chart fills.
const LINE = '#1b5fd9'

type View = 'forecast' | 'profile'

// Wrapper: the forecast and its inputs (the household Profile) live behind one
// nav entry, switched by an in-page sub-tab.
export function Forecast() {
  const { intent } = useNav()
  const [view, setView] = useState<View>(intent?.view === 'profile' ? 'profile' : 'forecast')
  return (
    <>
      <div className="subtabs">
        {(['forecast', 'profile'] as const).map((v) => (
          <button
            key={v}
            className={`subtab${view === v ? ' active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'forecast' ? 'Forecast' : 'Profile'}
          </button>
        ))}
      </div>
      {view === 'forecast' ? <ForecastView onEditProfile={() => setView('profile')} /> : <Profile />}
    </>
  )
}

function ForecastView({ onEditProfile }: { onEditProfile: () => void }) {
  const { format, formatCompact } = useCurrency()
  const [horizon, setHorizon] = useState(10)
  const [real, setReal] = useState(true)

  const query = useForecast({ horizon_years: horizon, real, n_paths: N_PATHS, seed: SEED })
  const result = query.data ?? null

  // Quarterly points for short horizons, yearly beyond 10y. x is months from today.
  const chartData = useMemo(() => {
    if (!result) return []
    const step = result.horizon_years <= 10 ? 3 : 12
    return result.bands
      .filter((b) => b.month % step === 0)
      .map((b: ForecastBand) => ({
        month: b.month,
        outer: [b.p10, b.p90] as [number, number],
        inner: [b.p25, b.p75] as [number, number],
        p50: b.p50,
        raw: b,
      }))
  }, [result])

  const yearTicks = useMemo(() => {
    if (!result) return []
    const n = result.horizon_years * 12
    const every = result.horizon_years <= 10 ? 12 : result.horizon_years <= 20 ? 24 : 60
    return Array.from({ length: Math.floor(n / every) + 1 }, (_, i) => i * every)
  }, [result])

  if (query.isLoading && !result) return <ForecastSkeleton />

  if (query.isError) {
    return (
      <div className="card">
        <h2 className="card-title">Forecast unavailable</h2>
        <div className="empty" style={{ marginTop: 12 }}>
          Could not run the forecast. Make sure the backend is running and the
          household profile row is seeded.
        </div>
      </div>
    )
  }

  const t = result?.terminal
  const yearOf = (m: number) => {
    const d = new Date()
    d.setMonth(d.getMonth() + m)
    return d.getFullYear()
  }

  return (
    <>
      <Goals results={result?.goals ?? []} real={real} />

      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Net-worth forecast</h2>
            <div className="card-meta">
              {N_PATHS.toLocaleString()} simulated futures from today&rsquo;s net worth. A range of
              what <em>could</em> happen, not a prediction.
            </div>
            {result && <ForecastInputsLine inputs={result.inputs} format={format} onEdit={onEditProfile} />}
          </div>
        </div>

        <div className="forecast-controls">
          <label className="forecast-control">
            <span className="tile-label">Horizon</span>
            <div className="segmented">
              {HORIZONS.map((h) => (
                <button key={h} className={horizon === h ? 'active' : ''} onClick={() => setHorizon(h)}>
                  {h}y
                </button>
              ))}
            </div>
          </label>
          <details className="forecast-advanced">
            <summary>Advanced</summary>
            <label className="forecast-control">
              <span className="tile-label">Terms</span>
              <div className="segmented">
                <button className={real ? 'active' : ''} onClick={() => setReal(true)}>Real</button>
                <button className={!real ? 'active' : ''} onClick={() => setReal(false)}>Nominal</button>
              </div>
            </label>
          </details>
          {result && result.horizon_years > horizon && (
            <span className="muted" style={{ fontSize: 12, alignSelf: 'center' }}>
              Showing {result.horizon_years}y to cover your furthest goal.
            </span>
          )}
        </div>

        <div className="networth-tiles">
          <div className="networth-tile">
            <div className="tile-label">Likely range in {result?.horizon_years ?? horizon}y</div>
            <div className="tile-value num" style={{ fontSize: 18 }}>
              {t ? `${formatCompact(t.p10)} – ${formatCompact(t.p90)}` : '—'}
            </div>
            <div className="health-sub">10th–90th percentile (80% of outcomes)</div>
          </div>
          <div className="networth-tile">
            <div className="tile-label">Median outcome (P50)</div>
            <div className="tile-value num" style={{ fontSize: 18 }}>{t ? format(t.p50) : '—'}</div>
            <div className="health-sub">A midpoint, not a promise: half above, half below</div>
          </div>
        </div>

        {chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={chartData} margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="g-fan-outer" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={LINE} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={LINE} stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={chart.grid.stroke} vertical={false} />
              <XAxis
                dataKey="month"
                type="number"
                domain={[0, (result?.horizon_years ?? horizon) * 12]}
                ticks={yearTicks}
                {...chart.axis}
                dy={6}
                tickFormatter={(m) => `'${String(yearOf(Number(m))).slice(2)}`}
              />
              <YAxis {...chart.axis} tickFormatter={(v) => formatCompact(Number(v))} width={56} />
              <Tooltip cursor={chart.cursor} content={<FanTooltip format={format} />} />
              <Area dataKey="outer" name="P10–P90" stroke="none" fill="url(#g-fan-outer)" isAnimationActive={false} />
              <Area dataKey="inner" name="P25–P75" stroke="none" fill={LINE} fillOpacity={0.16} isAnimationActive={false} />
              <Line type="monotone" dataKey="p50" name="Median" stroke={LINE} strokeWidth={2} dot={false} isAnimationActive={false} />
              {(result?.goals ?? []).filter((g) => g.probability != null).map((g) => (
                <ReferenceDot
                  key={`${g.month}-${g.label}-${g.amount}`}
                  x={g.months_away}
                  y={g.amount_base}
                  r={5}
                  fill="var(--surface)"
                  stroke={probColor(g.probability)}
                  strokeWidth={2}
                  label={{ value: g.label || 'goal', position: 'top', fill: 'var(--text-muted)', fontSize: 11 }}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        )}

        <div className="card-meta" style={{ marginTop: 14 }}>
          Bands widen with time because uncertainty compounds. Circles are your goals. Spending and
          the asset mix come from your data; income, planned expenses and settings from your Profile.{' '}
          {result?.real ? 'Values are in today\'s money.' : 'Values are nominal (not inflation-adjusted).'}
        </div>
      </div>
    </>
  )
}

interface FanTooltipProps {
  active?: boolean
  payload?: { payload: { raw: ForecastBand } }[]
  format: (n: number) => string
}

// One line saying where the forecast's inputs came from, with a way to change them.
function ForecastInputsLine({
  inputs, format, onEdit,
}: { inputs: ForecastResult['inputs']; format: (n: number) => string; onEdit: () => void }) {
  const spend =
    inputs.spending_source === 'override'
      ? `${format(inputs.monthly_spending)}/mo spending (your override)`
      : inputs.spending_source === 'derived'
        ? `${format(inputs.monthly_spending)}/mo spending (avg of ${inputs.spending_months} months)`
        : 'no spending data'
  const mix = ['equity', 'bonds', 'cash']
    .map((k) => `${Math.round((inputs.allocation[k] ?? 0) * 100)}% ${k}`)
    .join(' · ')
  const planned = inputs.planned_expenses
    ? ` · ${inputs.planned_expenses} planned ${inputs.planned_expenses === 1 ? 'expense' : 'expenses'}`
    : ''
  return (
    <div className="forecast-inputs">
      Using {format(inputs.monthly_income)}/mo income · {spend} · {mix}{planned}.{' '}
      <button className="link-btn" onClick={onEdit}>Edit profile</button>
    </div>
  )
}

function FanTooltip({ active, payload, format }: FanTooltipProps) {
  if (!active || !payload?.length) return null
  const raw = payload[0]?.payload?.raw
  if (!raw) return null
  const rows: [string, number][] = [
    ['P90 (optimistic)', raw.p90],
    ['P50 (median)', raw.p50],
    ['P10 (pessimistic)', raw.p10],
  ]
  return (
    <div
      style={{
        background: 'var(--surface-raised)',
        border: '1px solid var(--surface-border)',
        borderRadius: 12,
        padding: '10px 14px',
        minWidth: 180,
        boxShadow: '0 8px 24px rgba(29,31,38,0.12)',
      }}
    >
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 8, fontWeight: 500 }}>
        {new Date(`${raw.date}T00:00:00`).toLocaleString('en-US', { month: 'short', year: 'numeric' })}
      </div>
      {rows.map(([name, value]) => (
        <div
          key={name}
          style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '2px 0' }}
        >
          <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{name}</span>
          <span className="num" style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13 }}>
            {format(value)}
          </span>
        </div>
      ))}
    </div>
  )
}

function ForecastSkeleton() {
  return (
    <div className="card">
      <div className="skel" style={{ height: 18, width: 180, marginBottom: 16 }} />
      <div className="skel" style={{ height: 56, marginBottom: 16 }} />
      <div className="skel" style={{ height: 88, marginBottom: 16 }} />
      <div className="skel" style={{ height: 300 }} />
    </div>
  )
}
