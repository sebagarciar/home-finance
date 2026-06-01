import { useEffect, useMemo, useState } from 'react'
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts'
import type { ForecastBand } from '../api/client'
import { useForecast } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { chart } from '../design/chartTheme'
import { Assumptions } from './Assumptions'

const HORIZONS = [10, 20, 30, 40]
const SEED = 42
const N_PATHS = 5000

// Net-worth green, matching the Portfolio history chart. Bands fade from the
// median outward; cobalt accent is reserved for CTAs, never chart fills.
const LINE = '#6fcf4a'

type View = 'forecast' | 'assumptions'

// Wrapper: the forecast and its inputs (Assumptions) live behind one sidebar
// entry, switched by an in-page sub-tab.
export function Forecast() {
  const [view, setView] = useState<View>('forecast')
  return (
    <>
      <div className="subtabs">
        {(['forecast', 'assumptions'] as const).map((v) => (
          <button
            key={v}
            className={`subtab${view === v ? ' active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'forecast' ? 'Forecast' : 'Assumptions'}
          </button>
        ))}
      </div>
      {view === 'forecast' ? <ForecastView /> : <Assumptions />}
    </>
  )
}

function ForecastView() {
  const { format, formatCompact, toDisplay } = useCurrency()

  const [horizon, setHorizon] = useState(30)
  const [real, setReal] = useState(true)
  // Target is entered in the displayed currency; converted to CLP for the API.
  const [targetInput, setTargetInput] = useState('')
  const [appliedTarget, setAppliedTarget] = useState('')

  // Debounce the target so we don't re-run on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setAppliedTarget(targetInput), 400)
    return () => clearTimeout(t)
  }, [targetInput])

  // 1 unit of display currency in CLP (inverse of toDisplay).
  const clpPerDisplay = 1 / (toDisplay(1) || 1)
  const targetClp = appliedTarget.trim() === '' ? null : Number(appliedTarget) * clpPerDisplay

  const query = useForecast({
    horizon_years: horizon,
    real,
    target: targetClp != null && Number.isFinite(targetClp) ? Math.round(targetClp) : null,
    n_paths: N_PATHS,
    seed: SEED,
  })

  const result = query.data ?? null

  const chartData = useMemo(() => {
    if (!result) return []
    // Values stay in base CLP; `format`/`formatCompact` apply the display
    // conversion. The CLP↔EUR toggle then only relabels the axis — the band
    // shape is identical, which is the correct behaviour for a display toggle.
    return result.bands
      .filter((b) => b.month % 12 === 0)
      .map((b: ForecastBand) => ({
        year: new Date(`${b.date}T00:00:00`).getFullYear(),
        outer: [b.p10, b.p90] as [number, number],
        inner: [b.p25, b.p75] as [number, number],
        p50: b.p50,
        raw: b,
      }))
  }, [result])

  if (query.isLoading && !result) return <ForecastSkeleton />

  if (query.isError) {
    return (
      <div className="card">
        <h2 className="card-title">Forecast unavailable</h2>
        <div className="empty" style={{ marginTop: 12 }}>
          Could not run the forecast. Make sure the backend is running and an
          assumptions row is seeded.
        </div>
      </div>
    )
  }

  const t = result?.terminal
  const prob = result?.prob_hit_target

  return (
    <>
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Net-worth forecast</h2>
            <div className="card-meta">
              {N_PATHS.toLocaleString()} simulated futures from today's net worth,
              compounding {real ? 'real (inflation-adjusted)' : 'nominal'} returns
              with income and spending shocks. A range of what <em>could</em>{' '}
              happen — not a prediction.
            </div>
          </div>
        </div>

        {/* Run controls */}
        <div className="forecast-controls">
          <label className="forecast-control">
            <span className="tile-label">Horizon</span>
            <div className="segmented">
              {HORIZONS.map((h) => (
                <button
                  key={h}
                  className={horizon === h ? 'active' : ''}
                  onClick={() => setHorizon(h)}
                >
                  {h}y
                </button>
              ))}
            </div>
          </label>

          <label className="forecast-control">
            <span className="tile-label">Terms</span>
            <div className="segmented">
              <button className={real ? 'active' : ''} onClick={() => setReal(true)}>
                Real
              </button>
              <button className={!real ? 'active' : ''} onClick={() => setReal(false)}>
                Nominal
              </button>
            </div>
          </label>

          <label className="forecast-control">
            <span className="tile-label">Target net worth</span>
            <input
              placeholder={`e.g. ${formatCompact(500_000_000)}`}
              value={targetInput}
              onChange={(e) => setTargetInput(e.target.value.replace(/[^0-9.]/g, ''))}
              inputMode="decimal"
            />
          </label>
        </div>

        {/* Headline tiles — probability first, the absolute median last. */}
        <div className="networth-tiles">
          <div className="networth-tile emphasis">
            <div className="tile-label">Chance of reaching target</div>
            <div className="tile-value num">
              {prob == null ? '—' : `${Math.round(prob * 100)}%`}
            </div>
            <div className="health-sub">
              {prob == null
                ? `Set a target to stress-test it`
                : `of paths end ≥ ${format(targetClp ?? 0)} in ${horizon}y`}
            </div>
          </div>
          <div className="networth-tile">
            <div className="tile-label">Likely range in {horizon}y</div>
            <div className="tile-value num" style={{ fontSize: 18 }}>
              {t ? `${formatCompact(t.p10)} – ${formatCompact(t.p90)}` : '—'}
            </div>
            <div className="health-sub">10th–90th percentile (80% of outcomes)</div>
          </div>
          <div className="networth-tile">
            <div className="tile-label">Median outcome (P50)</div>
            <div className="tile-value num" style={{ fontSize: 18 }}>
              {t ? format(t.p50) : '—'}
            </div>
            <div className="health-sub">A midpoint, not a promise — half above, half below</div>
          </div>
        </div>

        {/* Fan chart */}
        {chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={chartData} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="g-fan-outer" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={LINE} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={LINE} stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={chart.grid.stroke} vertical={false} />
              <XAxis
                dataKey="year"
                {...chart.axis}
                dy={6}
                tickFormatter={(v) => `'${String(v).slice(2)}`}
              />
              <YAxis {...chart.axis} tickFormatter={(v) => formatCompact(Number(v))} width={56} />
              <Tooltip
                cursor={chart.cursor}
                content={<FanTooltip format={format} />}
              />
              {targetClp != null && Number.isFinite(targetClp) && (
                <ReferenceLine
                  y={targetClp}
                  stroke="var(--text-muted)"
                  strokeDasharray="4 4"
                  label={{ value: 'target', position: 'right', fill: 'var(--text-muted)', fontSize: 11 }}
                />
              )}
              <Area
                dataKey="outer"
                name="P10–P90"
                stroke="none"
                fill="url(#g-fan-outer)"
                isAnimationActive={false}
              />
              <Area
                dataKey="inner"
                name="P25–P75"
                stroke="none"
                fill={LINE}
                fillOpacity={0.16}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="p50"
                name="Median"
                stroke={LINE}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}

        <div className="card-meta" style={{ marginTop: 14 }}>
          Bands widen with time because uncertainty compounds. Inputs (salaries,
          growth, allocation, ρ, inflation) come from your assumptions — editing
          them lands in a later phase. {result?.real ? 'Values are in today\'s money.' : 'Values are nominal (not inflation-adjusted).'}
        </div>
      </div>
    </>
  )
}

interface FanTooltipProps {
  active?: boolean
  label?: number | string
  payload?: { payload: { raw: ForecastBand } }[]
  format: (n: number) => string
}

function FanTooltip({ active, payload, label, format }: FanTooltipProps) {
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
        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      }}
    >
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 8, fontWeight: 500 }}>
        {`Year '${String(label).slice(2)}`}
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
