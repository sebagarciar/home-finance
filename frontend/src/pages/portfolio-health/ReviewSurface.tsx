import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type PortfolioReview, type ReviewResponse, type SecurityMetadata, type SecurityMetadataInput } from '../../api/client'
import { queryKeys, useSecurityMetadata } from '../../api/hooks'
import { useCurrency } from '../../lib/currency'
import { SEVERITY_RANK, SUBSCORE_LABELS } from './constants'
import { LiquiditySection } from './LiquiditySection'
import { StressSection } from './StressSection'

export function ReviewSurface({ review, onEdit }: { review: PortfolioReview | null; onEdit: () => void }) {
  const qc = useQueryClient()
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setErr(null)
    try {
      const res: ReviewResponse = await api.portfolioHealth.runReview()
      if (res.profile_incomplete) {
        setErr('Profile is incomplete — please complete it first.')
      }
      await qc.invalidateQueries({ queryKey: queryKeys.portfolioReviewLatest() })
      await qc.invalidateQueries({ queryKey: queryKeys.portfolioReviews() })
      await qc.invalidateQueries({ queryKey: queryKeys.securityMetadata() })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to run review')
    } finally {
      setRunning(false)
    }
  }

  if (review == null) {
    return (
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Portfolio Health Review</h2>
            <div className="card-meta">Your profile is saved. Run a review to evaluate your current portfolio.</div>
          </div>
          <button className="btn primary" onClick={run} disabled={running}>
            {running ? 'Running…' : 'Run review'}
          </button>
        </div>
        {err && <div className="form-error">{err}</div>}
      </div>
    )
  }

  return (
    <ReviewView review={review} onEdit={onEdit} onRerun={run} running={running} err={err} />
  )
}

function ReviewView({
  review, onEdit, onRerun, running, err,
}: {
  review: PortfolioReview; onEdit: () => void; onRerun: () => void; running: boolean; err: string | null
}) {
  const { format } = useCurrency()
  const d = review.diagnostics
  const status = d.status ?? '—'
  const tone = statusTone(status)

  const sortedFindings = [...review.findings].sort(
    (a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9),
  )
  const topIssues = sortedFindings.slice(0, 3)
  const strengths = Object.entries(review.sub_scores)
    .filter(([, v]) => v >= 85)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)

  const buckets = ['cash', 'bonds', 'global_equities', 'alternatives', 'crypto']
  const labels: Record<string, string> = {
    cash: 'Cash', bonds: 'Bonds', global_equities: 'Equities', alternatives: 'Alternatives', crypto: 'Crypto',
  }

  return (
    <>
      {/* Status banner */}
      <div className={`card phr-banner ${tone}`}>
        <div>
          <div className="tile-label">Overall status</div>
          <div className="phr-status">{status}</div>
          <div className="card-meta" style={{ marginTop: 6 }}>
            A diagnostic estimate based on the data available — not a precise truth, and not advice.
          </div>
        </div>
        <div className="phr-score-wrap">
          <div className="phr-score num">{Math.round(review.overall_score)}</div>
          <div className="tile-label">Health score / 100</div>
        </div>
        <div className="phr-actions">
          <button className="btn" onClick={onEdit}>Edit profile</button>
          <button className="btn primary" onClick={onRerun} disabled={running}>
            {running ? 'Running…' : 'Re-run'}
          </button>
        </div>
      </div>
      {err && <div className="form-error" style={{ marginBottom: 12 }}>{err}</div>}

      {/* Sub-scores */}
      <div className="card">
        <div className="card-header"><h2 className="card-title">Score breakdown</h2></div>
        <div className="networth-tiles">
          {Object.entries(review.sub_scores).map(([k, v]) => (
            <div className="networth-tile" key={k}>
              <div className="tile-label">{SUBSCORE_LABELS[k] ?? k}</div>
              <div className="tile-value num" style={{ fontSize: 22 }}>{Math.round(v)}</div>
              <div className="phr-meter"><div className="phr-meter-fill" style={{ width: `${v}%` }} /></div>
            </div>
          ))}
        </div>
      </div>

      {/* Strengths + issues */}
      <div className="grid-2">
        <div className="card">
          <div className="card-header"><h2 className="card-title">Top strengths</h2></div>
          {strengths.length === 0 ? (
            <div className="empty">No standout strengths yet — see the issues to improve alignment.</div>
          ) : (
            <ul className="phr-list">
              {strengths.map(([k, v]) => (
                <li key={k}><span className="phr-sev sev-low">good</span>
                  Strong {(SUBSCORE_LABELS[k] ?? k).toLowerCase()} ({Math.round(v)}/100)</li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <div className="card-header"><h2 className="card-title">Top issues</h2></div>
          {topIssues.length === 0 ? (
            <div className="empty">No issues found against your policy.</div>
          ) : (
            <ul className="phr-list">
              {topIssues.map((f, i) => (
                <li key={i}><span className={`phr-sev sev-${f.severity}`}>{f.severity}</span>{f.finding}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Allocation review */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Allocation review</h2>
          <div className="card-meta">Current allocation vs your policy target ranges.</div>
        </div>
        <div className="phr-alloc">
          {buckets.map((b) => {
            const cur = d.allocation.current_pct[b] ?? 0
            const range = d.allocation.target_ranges[b] ?? [0, 0]
            const out = d.allocation.out_of_range.find((o) => o.bucket === b)
            return (
              <div className="phr-alloc-row" key={b}>
                <div className="phr-alloc-label">{labels[b] ?? b}</div>
                <div className="phr-bar">
                  <div className="phr-bar-range" style={{ left: `${range[0]}%`, width: `${Math.max(range[1] - range[0], 0.5)}%` }} />
                  <div className={`phr-bar-fill${out ? ' off' : ''}`} style={{ width: `${Math.min(cur, 100)}%` }} />
                </div>
                <div className="phr-alloc-val num">{cur.toFixed(1)}%</div>
                <div className="phr-alloc-target">{range[0]}–{range[1]}%</div>
                {out
                  ? <span className="phr-sev sev-medium">{out.direction}</span>
                  : <span className="phr-sev sev-low">in range</span>}
              </div>
            )
          })}
        </div>
      </div>

      {/* Concentration review */}
      <div className="card">
        <div className="card-header"><h2 className="card-title">Concentration review</h2></div>
        <div className="networth-tiles">
          <ConcTile label="Largest holding"
            value={d.concentration.largest_holding ? `${d.concentration.largest_holding.ticker} · ${d.concentration.largest_holding.pct.toFixed(1)}%` : '—'} />
          <ConcTile label="Top 3 holdings" value={`${d.concentration.top3_pct.toFixed(1)}%`} />
          <ConcTile label="Top 5 holdings" value={`${d.concentration.top5_pct.toFixed(1)}%`} />
          <ConcTile label="Crypto exposure" value={`${d.concentration.crypto_pct.toFixed(1)}%`} />
          {d.concentration.employer_stock_ticker && (
            <ConcTile label={`Employer (${d.concentration.employer_stock_ticker})`}
              value={`${d.concentration.employer_stock_pct.toFixed(1)}%`} />
          )}
        </div>
        <div className="card-meta" style={{ marginTop: 10 }}>
          Portfolio value evaluated: {format(Number(d.allocation.portfolio_value_in_base))}.
        </div>
      </div>

      {/* Sector concentration */}
      {d.sector && Object.keys(d.sector.by_sector_pct).length > 0 && (
        <ExposureBreakdown
          title="Sector exposure"
          meta="Single-stock concentration by sector. Diversified funds are excluded."
          items={d.sector.by_sector_pct}
          limit={d.sector.max_sector_pct}
        />
      )}

      {/* Geography concentration */}
      {d.geography && Object.keys(d.geography.by_country_pct).length > 0 && (
        <ExposureBreakdown
          title="Geographic exposure"
          meta="Country concentration from holdings with enriched metadata."
          items={d.geography.by_country_pct}
          limit={d.geography.max_country_pct}
        />
      )}

      {/* Currency exposure */}
      {d.currency_exposure && Object.keys(d.currency_exposure.by_currency_pct).length > 0 && (
        <ExposureBreakdown
          title="Currency exposure"
          meta="FX exposure across all cash and holdings."
          items={d.currency_exposure.by_currency_pct}
          limit={d.currency_exposure.max_currency_pct}
        />
      )}

      {/* Fees */}
      {d.fees && <FeesSection fees={d.fees} />}

      {/* Liquidity / Emergency fund */}
      {d.liquidity && <LiquiditySection liq={d.liquidity} format={format} />}

      {/* Stress scenarios */}
      {d.stress && d.stress.length > 0 && <StressSection scenarios={d.stress} format={format} />}

      {/* Findings */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Findings</h2>
          <div className="card-meta">{review.findings.length} finding(s). Each is an educational review point, not an instruction.</div>
        </div>
        {review.findings.length === 0 ? (
          <div className="empty">No findings — your portfolio looks aligned with your policy.</div>
        ) : (
          <div className="phr-findings">
            {sortedFindings.map((f, i) => (
              <div className="phr-finding" key={i}>
                <div className="phr-finding-head">
                  <span className={`phr-sev sev-${f.severity}`}>{f.severity}</span>
                  <span className="phr-cat">{f.category.replace(/_/g, ' ')}</span>
                </div>
                <div className="phr-finding-title">{f.finding}</div>
                <div className="phr-finding-body"><strong>Why it matters:</strong> {f.whyItMatters}</div>
                <div className="phr-finding-body muted">{f.educationalGuidance}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Missing data */}
      {review.missing_data.length > 0 && (
        <div className="card">
          <div className="card-header"><h2 className="card-title">Data limitations</h2></div>
          <ul className="phr-list">
            {review.missing_data.map((m, i) => <li key={i}><span className="phr-sev sev-low">data</span>{m}</li>)}
          </ul>
          <div className="card-meta" style={{ marginTop: 8 }}>
            Missing data limits review accuracy. Set asset classes and prices on your holdings to improve it.
          </div>
        </div>
      )}

      {/* AI explanation */}
      {review.ai_explanation && <AiExplanationCard exp={review.ai_explanation as unknown as AiExplanation} />}

      {/* Security metadata editor */}
      <MetadataEditor />

      <div className="card-meta" style={{ padding: '0 4px 8px' }}>
        This review is educational and based on a deterministic rules engine (v{review.rules_engine_version}).
        It does not recommend specific securities or trades. For decisions involving your specific
        situation, consider speaking with a licensed financial advisor.
      </div>
    </>
  )
}

// --------------------------------------------------------------------------- //
// Exposure breakdown (sector / geography / currency)
// --------------------------------------------------------------------------- //
function ExposureBreakdown({
  title, meta, items, limit,
}: {
  title: string; meta: string; items: Record<string, number>; limit: number
}) {
  const sorted = Object.entries(items).sort((a, b) => b[1] - a[1])
  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">{title}</h2>
        <div className="card-meta">{meta}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
        {sorted.map(([label, pct]) => {
          const over = pct > limit + 0.001
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ width: 120, fontSize: 13, color: 'var(--text-secondary)', flexShrink: 0 }}>{label}</div>
              <div style={{ flex: 1, position: 'relative', height: 8, background: 'var(--surface-hover)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  position: 'absolute', left: 0, top: 0, height: '100%',
                  width: `${Math.min(pct, 100)}%`,
                  background: over ? 'var(--negative-text)' : 'var(--cat-1)',
                  borderRadius: 4,
                  transition: 'width 0.3s',
                }} />
                {/* limit marker */}
                <div style={{
                  position: 'absolute', left: `${limit}%`, top: 0, height: '100%',
                  width: 1, background: 'var(--text-faint)',
                }} />
              </div>
              <div className="num" style={{
                width: 52, textAlign: 'right', fontSize: 13, fontWeight: 600,
                color: over ? 'var(--negative-text)' : 'var(--text-primary)',
                flexShrink: 0,
              }}>
                {pct.toFixed(1)}%
              </div>
              {over && <span className="phr-sev sev-medium" style={{ flexShrink: 0 }}>over limit</span>}
            </div>
          )
        })}
      </div>
      <div className="card-meta" style={{ marginTop: 10 }}>
        Policy limit: {limit}%. The grey line marks the limit.
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Fees section
// --------------------------------------------------------------------------- //
function FeesSection({ fees }: {
  fees: {
    weighted_expense_ratio: number | null
    fee_coverage_pct: number | null
    holdings_with_fee_data: number
    holdings_missing_fee_data: number
    fee_warn_threshold: number
    fee_high_threshold: number
  }
}) {
  const hasData = fees.weighted_expense_ratio !== null
  const isHigh = hasData && fees.weighted_expense_ratio! >= fees.fee_high_threshold
  const isWarn = hasData && !isHigh && fees.weighted_expense_ratio! >= fees.fee_warn_threshold
  const erColor = isHigh ? 'var(--negative-text)' : isWarn ? 'var(--pending-text)' : 'var(--positive-text)'

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Cost efficiency</h2>
        <div className="card-meta">Weighted-average expense ratio across non-crypto holdings.</div>
      </div>
      <div className="networth-tiles">
        <div className="networth-tile">
          <div className="tile-label">Weighted avg ER</div>
          <div className="tile-value num" style={{ fontSize: 22, color: hasData ? erColor : 'var(--text-muted)' }}>
            {hasData ? `${fees.weighted_expense_ratio!.toFixed(2)}%` : '—'}
          </div>
          {hasData && (
            <div style={{ fontSize: 11, color: erColor, marginTop: 2 }}>
              {isHigh ? 'High — review costs' : isWarn ? 'Above reference level' : 'Within range'}
            </div>
          )}
        </div>
        <div className="networth-tile">
          <div className="tile-label">Fee data coverage</div>
          <div className="tile-value num" style={{ fontSize: 22 }}>
            {fees.fee_coverage_pct !== null ? `${fees.fee_coverage_pct.toFixed(0)}%` : '—'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
            {fees.holdings_with_fee_data} / {fees.holdings_with_fee_data + fees.holdings_missing_fee_data} holdings
          </div>
        </div>
        <div className="networth-tile">
          <div className="tile-label">Reference levels</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
            <div>Warn: &gt;{fees.fee_warn_threshold}%</div>
            <div>High: &gt;{fees.fee_high_threshold}%</div>
          </div>
        </div>
      </div>
      {!hasData && fees.holdings_missing_fee_data > 0 && (
        <div className="card-meta" style={{ marginTop: 8 }}>
          No fee data for any holdings. Add expense ratios via the metadata editor below to enable cost analysis.
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Security metadata editor
// --------------------------------------------------------------------------- //
function MetadataEditor() {
  const qc = useQueryClient()
  const { data: rows, isLoading } = useSecurityMetadata()
  const [editing, setEditing] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<SecurityMetadataInput & { ticker?: string }>({})
  const [enriching, setEnriching] = useState(false)

  const openEdit = (row: SecurityMetadata) => {
    setForm({
      ticker: row.ticker,
      sector: row.sector ?? '',
      country: row.country ?? '',
      expense_ratio: row.expense_ratio ?? undefined,
      diversified_fund: row.diversified_fund ?? undefined,
      asset_class: row.asset_class ?? '',
      region: row.region ?? '',
      currency: row.currency ?? '',
      product_type: row.product_type ?? '',
    })
    setEditing(row.ticker)
  }

  const save = async () => {
    if (!editing) return
    setSaving(true)
    try {
      const body: SecurityMetadataInput = {}
      if (form.sector !== undefined && form.sector !== '') body.sector = form.sector
      if (form.country !== undefined && form.country !== '') body.country = (form.country as string).toUpperCase().slice(0, 2)
      if (form.expense_ratio !== undefined && form.expense_ratio !== null) body.expense_ratio = Number(form.expense_ratio)
      if (form.diversified_fund !== undefined) body.diversified_fund = form.diversified_fund
      if (form.asset_class !== undefined && form.asset_class !== '') body.asset_class = form.asset_class
      if (form.region !== undefined && form.region !== '') body.region = form.region
      await api.portfolioHealth.putMetadata(editing, body)
      await qc.invalidateQueries({ queryKey: queryKeys.securityMetadata() })
      setEditing(null)
    } finally {
      setSaving(false)
    }
  }

  const triggerEnrich = async () => {
    setEnriching(true)
    try {
      await api.portfolioHealth.triggerEnrich()
      await qc.invalidateQueries({ queryKey: queryKeys.securityMetadata() })
    } finally {
      setEnriching(false)
    }
  }

  if (isLoading) return null

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Security metadata</h2>
          <div className="card-meta">Sector, country, and expense ratios used for the enriched findings above.</div>
        </div>
        <button className="btn" onClick={triggerEnrich} disabled={enriching}>
          {enriching ? 'Enriching…' : 'Re-enrich from yfinance'}
        </button>
      </div>

      {(!rows || rows.length === 0) ? (
        <div className="empty">
          No metadata cached yet. Run a review to auto-enrich from yfinance, or add overrides manually.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="txn-table" style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr>
                <th>Ticker</th><th>Type</th><th>Sector</th><th>Country</th>
                <th>ER %</th><th>Diversified</th><th>Source</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                editing === row.ticker ? (
                  <tr key={row.ticker}>
                    <td className="num">{row.ticker}</td>
                    <td>
                      <input className="form-input" style={{ width: 90 }}
                        value={form.asset_class as string ?? ''}
                        onChange={e => setForm(f => ({ ...f, asset_class: e.target.value }))}
                        placeholder="equity, etf…" />
                    </td>
                    <td>
                      <input className="form-input" style={{ width: 110 }}
                        value={form.sector as string ?? ''}
                        onChange={e => setForm(f => ({ ...f, sector: e.target.value }))}
                        placeholder="Technology…" />
                    </td>
                    <td>
                      <input className="form-input" style={{ width: 50 }}
                        value={form.country as string ?? ''}
                        onChange={e => setForm(f => ({ ...f, country: e.target.value.toUpperCase() }))}
                        placeholder="US" maxLength={2} />
                    </td>
                    <td>
                      <input className="form-input" style={{ width: 70 }} type="number" step="0.01"
                        value={form.expense_ratio as number ?? ''}
                        onChange={e => setForm(f => ({ ...f, expense_ratio: e.target.value === '' ? undefined : Number(e.target.value) }))}
                        placeholder="0.03" />
                    </td>
                    <td>
                      <select className="form-input" style={{ width: 90 }}
                        value={form.diversified_fund === undefined ? '' : String(form.diversified_fund)}
                        onChange={e => setForm(f => ({ ...f, diversified_fund: e.target.value === '' ? undefined : e.target.value === 'true' }))}>
                        <option value="">—</option>
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    </td>
                    <td colSpan={2} style={{ display: 'flex', gap: 6, padding: '6px 0' }}>
                      <button className="btn primary" onClick={save} disabled={saving}>{saving ? '…' : 'Save'}</button>
                      <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={row.ticker}>
                    <td className="num" style={{ fontWeight: 600 }}>{row.ticker}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{row.product_type ?? row.asset_class ?? '—'}</td>
                    <td>{row.sector ?? <span style={{ color: 'var(--text-muted)' }}>—</span>}</td>
                    <td>{row.country ?? <span style={{ color: 'var(--text-muted)' }}>—</span>}</td>
                    <td className="num">{row.expense_ratio !== null ? `${row.expense_ratio}%` : <span style={{ color: 'var(--text-muted)' }}>—</span>}</td>
                    <td>{row.diversified_fund === null ? <span style={{ color: 'var(--text-muted)' }}>—</span> : row.diversified_fund ? 'Yes' : 'No'}</td>
                    <td>
                      <span className="phr-sev" style={{
                        background: row.source === 'manual' ? 'var(--accent-bg)' : 'var(--surface-raised)',
                        color: row.source === 'manual' ? 'var(--accent)' : 'var(--text-muted)',
                        fontSize: 11, padding: '2px 7px', borderRadius: 999,
                      }}>
                        {row.source}
                      </span>
                    </td>
                    <td>
                      <button className="btn" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => openEdit(row)}>
                        Edit
                      </button>
                    </td>
                  </tr>
                )
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// AI explanation
// --------------------------------------------------------------------------- //
interface AiExplanation {
  generated_by: 'ollama' | 'template'
  overall_summary?: string
  aligned?: string
  needs_attention?: string
  why_it_matters?: string
  what_to_review_next?: string
  data_limitations?: string
  professional_advice_note?: string
}

function AiExplanationCard({ exp }: { exp: AiExplanation }) {
  const isAi = exp.generated_by === 'ollama'
  const sections: { key: keyof AiExplanation; label: string }[] = [
    { key: 'overall_summary', label: 'Summary' },
    { key: 'aligned', label: "What's working" },
    { key: 'needs_attention', label: 'Needs attention' },
    { key: 'why_it_matters', label: 'Why these matter' },
    { key: 'what_to_review_next', label: 'What to review next' },
    { key: 'data_limitations', label: 'Data limitations' },
    { key: 'professional_advice_note', label: 'Advice note' },
  ]

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Review narrative</h2>
        <span className="phr-sev" style={{
          background: isAi ? 'var(--accent-bg)' : 'var(--surface-raised)',
          color: isAi ? 'var(--accent)' : 'var(--text-muted)',
          fontSize: 11,
          padding: '2px 8px',
          borderRadius: 999,
          fontWeight: 500,
          letterSpacing: '0.04em',
        }}>
          {isAi ? 'AI-generated' : 'template'}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 4 }}>
        {sections.map(({ key, label }) => {
          const text = exp[key] as string | undefined
          if (!text) return null
          return (
            <div key={key}>
              <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                {label}
              </div>
              <div style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, whiteSpace: 'pre-line' }}>
                {text}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ConcTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="networth-tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value num" style={{ fontSize: 20 }}>{value}</div>
    </div>
  )
}

function statusTone(status: string): string {
  if (status === 'Looks aligned') return 'pos'
  if (status === 'Monitor') return 'warn'
  return 'neg'
}
