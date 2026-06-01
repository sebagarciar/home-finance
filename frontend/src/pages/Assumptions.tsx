import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type Assumptions as AssumptionsData, type AssumptionsUpdate } from '../api/client'
import { useAssumptions, useSpendingSummary } from '../api/hooks'

const CURRENCIES = ['CLP', 'EUR', 'USD', 'GBP']

// Flat string-based form state — keeps inputs simple; parsed back on save.
interface Form {
  income1: string; income1ccy: string
  income2: string; income2ccy: string
  incomeGrowthPct: string; incomeSigma: string
  spending: string; spendingCcy: string
  spendingGrowthPct: string
  retEquityPct: string; retBondsPct: string; retCashPct: string
  allocEquityPct: string; allocBondsPct: string; allocCashPct: string
  horizon: string; rho: string; inflationPct: string; fxDriftPct: string
}

const pct = (d: number) => String(Math.round(d * 1000) / 10) // 0.07 -> "7"
const num = (s: string) => (s.trim() === '' ? 0 : Number(s))

function seedForm(a: AssumptionsData): Form {
  return {
    income1: a.income_user1, income1ccy: a.income_user1_currency,
    income2: a.income_user2, income2ccy: a.income_user2_currency,
    incomeGrowthPct: pct(a.income_growth_rate), incomeSigma: String(a.income_noise_sigma),
    spending: a.spending_baseline_monthly, spendingCcy: a.spending_baseline_currency,
    spendingGrowthPct: pct(a.spending_growth_rate),
    retEquityPct: pct(a.return_assumptions.equity ?? 0),
    retBondsPct: pct(a.return_assumptions.bonds ?? 0),
    retCashPct: pct(a.return_assumptions.cash ?? 0),
    allocEquityPct: pct(a.asset_allocation.equity ?? 0),
    allocBondsPct: pct(a.asset_allocation.bonds ?? 0),
    allocCashPct: pct(a.asset_allocation.cash ?? 0),
    horizon: String(a.horizon_years), rho: String(a.correlation_rho),
    inflationPct: pct(a.inflation_rate), fxDriftPct: pct(a.fx_drift_annual),
  }
}

// Container: gate on the loaded row so the form's useState initializer reads it
// exactly once (no seeding-via-effect).
export function Assumptions() {
  const assumptionsQ = useAssumptions()
  if (!assumptionsQ.data) return <AssumptionsSkeleton />
  return <AssumptionsForm initial={assumptionsQ.data} />
}

function AssumptionsForm({ initial }: { initial: AssumptionsData }) {
  const qc = useQueryClient()
  const summaryQ = useSpendingSummary()

  const [form, setForm] = useState<Form>(() => seedForm(initial))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Suggested monthly figures from the last (up to 12) statemented months.
  const suggestions = useMemo(() => {
    const s = summaryQ.data
    if (!s) return null
    const avg = (rows: { total: string }[]) => {
      const last = [...rows].slice(-12)
      if (last.length === 0) return null
      return Math.round(last.reduce((acc, r) => acc + Number(r.total), 0) / last.length)
    }
    return { spend: avg(s.by_month), income: avg(s.by_month_income) }
  }, [summaryQ.data])

  const set = (patch: Partial<Form>) => {
    setForm((prev) => ({ ...prev, ...patch }))
    setSaved(false)
  }

  const allocSum =
    num(form.allocEquityPct) + num(form.allocBondsPct) + num(form.allocCashPct)

  const save = async () => {
    setSaving(true); setErr(null)
    const payload: AssumptionsUpdate = {
      income_user1: form.income1 || '0', income_user1_currency: form.income1ccy,
      income_user2: form.income2 || '0', income_user2_currency: form.income2ccy,
      income_growth_rate: num(form.incomeGrowthPct) / 100,
      income_noise_sigma: num(form.incomeSigma),
      spending_baseline_monthly: form.spending || '0', spending_baseline_currency: form.spendingCcy,
      spending_growth_rate: num(form.spendingGrowthPct) / 100,
      return_assumptions: {
        equity: num(form.retEquityPct) / 100,
        bonds: num(form.retBondsPct) / 100,
        cash: num(form.retCashPct) / 100,
      },
      asset_allocation: {
        equity: num(form.allocEquityPct) / 100,
        bonds: num(form.allocBondsPct) / 100,
        cash: num(form.allocCashPct) / 100,
      },
      horizon_years: Math.round(num(form.horizon)),
      correlation_rho: num(form.rho),
      inflation_rate: num(form.inflationPct) / 100,
      fx_drift_annual: num(form.fxDriftPct) / 100,
    }
    try {
      await api.assumptions.update(payload)
      // Refresh the row + force the forecast to recompute with new inputs.
      await qc.invalidateQueries({ queryKey: ['assumptions'] })
      await qc.invalidateQueries({ queryKey: ['forecast'] })
      setSaved(true)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Forecast assumptions</h2>
            <div className="card-meta">
              The forecast reads these — not your transaction history (which is
              only partial). Set your real monthly figures here, then check the
              Forecast tab. The "use my data" links fill from your statemented months.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {saved && <span className="tag tag-info">Saved ✓</span>}
            <button className="btn primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
        {err && <div className="form-error" style={{ marginBottom: 12 }}>{err}</div>}

        <div className="grid-2">
          {/* Income */}
          <Section title="Income" subtitle="Net monthly take-home per person.">
            <MoneyField
              label="Person 1 — monthly"
              value={form.income1}
              ccy={form.income1ccy}
              onValue={(v) => set({ income1: v })}
              onCcy={(c) => set({ income1ccy: c })}
              hint={
                suggestions?.income != null
                  ? { text: `use my avg (${suggestions.income.toLocaleString('es-CL')} CLP)`,
                      onClick: () => set({ income1: String(suggestions.income), income1ccy: 'CLP' }) }
                  : undefined
              }
            />
            <MoneyField
              label="Person 2 — monthly"
              value={form.income2}
              ccy={form.income2ccy}
              onValue={(v) => set({ income2: v })}
              onCcy={(c) => set({ income2ccy: c })}
            />
            <PctField label="Annual income growth" value={form.incomeGrowthPct} onChange={(v) => set({ incomeGrowthPct: v })} />
            <PlainField label="Income noise σ (0–1)" value={form.incomeSigma} onChange={(v) => set({ incomeSigma: v })} hintText="Month-to-month volatility. 0.05 ≈ small wobble." />
          </Section>

          {/* Spending */}
          <Section title="Spending" subtitle="Typical total monthly outflow (ex-salary).">
            <MoneyField
              label="Baseline — monthly"
              value={form.spending}
              ccy={form.spendingCcy}
              onValue={(v) => set({ spending: v })}
              onCcy={(c) => set({ spendingCcy: c })}
              hint={
                suggestions?.spend != null
                  ? { text: `use my avg (${suggestions.spend.toLocaleString('es-CL')} CLP)`,
                      onClick: () => set({ spending: String(suggestions.spend), spendingCcy: 'CLP' }) }
                  : undefined
              }
            />
            <PctField label="Annual spending growth" value={form.spendingGrowthPct} onChange={(v) => set({ spendingGrowthPct: v })} />
          </Section>

          {/* Returns & allocation */}
          <Section
            title="Returns & allocation"
            subtitle={`Expected annual return and portfolio weight per asset class. Allocation sums to ${Math.round(allocSum)}%.`}
          >
            <BucketRow label="Equity" ret={form.retEquityPct} alloc={form.allocEquityPct}
              onRet={(v) => set({ retEquityPct: v })} onAlloc={(v) => set({ allocEquityPct: v })} />
            <BucketRow label="Bonds" ret={form.retBondsPct} alloc={form.allocBondsPct}
              onRet={(v) => set({ retBondsPct: v })} onAlloc={(v) => set({ allocBondsPct: v })} />
            <BucketRow label="Cash" ret={form.retCashPct} alloc={form.allocCashPct}
              onRet={(v) => set({ retCashPct: v })} onAlloc={(v) => set({ allocCashPct: v })} />
            {Math.abs(allocSum - 100) > 0.5 && (
              <div className="muted" style={{ fontSize: 12 }}>
                Weights don't sum to 100% — they'll be normalized when the forecast runs.
              </div>
            )}
            <div className="muted" style={{ fontSize: 12 }}>
              Equity/bonds drive the historical bootstrap (VT/AGG); the return % is
              the fallback used when market history can't be fetched. Cash uses its
              return directly.
            </div>
          </Section>

          {/* Forecast parameters */}
          <Section title="Forecast parameters" subtitle="Horizon and the stress levers.">
            <PlainField label="Horizon (years)" value={form.horizon} onChange={(v) => set({ horizon: v })} />
            <PctField label="Inflation (annual)" value={form.inflationPct} onChange={(v) => set({ inflationPct: v })} />
            <PlainField label="Correlation ρ (0–1)" value={form.rho} onChange={(v) => set({ rho: v })} hintText="How hard bad-market months hit income & spending. Default 0.3." />
            <PctField label="CLP FX drift (annual)" value={form.fxDriftPct} onChange={(v) => set({ fxDriftPct: v })} hintText="0 = flat. Only affects foreign-currency income." />
          </Section>
        </div>
      </div>
    </>
  )
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="assumptions-section">
      <div className="assumptions-section-head">
        <h3 className="card-title" style={{ fontSize: 14 }}>{title}</h3>
        {subtitle && <div className="card-meta">{subtitle}</div>}
      </div>
      <div className="assumptions-fields">{children}</div>
    </div>
  )
}

function MoneyField({
  label, value, ccy, onValue, onCcy, hint,
}: {
  label: string; value: string; ccy: string
  onValue: (v: string) => void; onCcy: (c: string) => void
  hint?: { text: string; onClick: () => void }
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {hint && (
          <button type="button" className="link-btn" style={{ marginLeft: 8 }} onClick={hint.onClick}>
            {hint.text}
          </button>
        )}
      </span>
      <div className="field-money">
        <input
          value={value}
          inputMode="decimal"
          onChange={(e) => onValue(e.target.value.replace(/[^0-9.]/g, ''))}
        />
        <select value={ccy} onChange={(e) => onCcy(e.target.value)}>
          {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
    </label>
  )
}

function PctField({ label, value, onChange, hintText }: { label: string; value: string; onChange: (v: string) => void; hintText?: string }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <div className="field-suffix">
        <input value={value} inputMode="decimal" onChange={(e) => onChange(e.target.value.replace(/[^0-9.-]/g, ''))} />
        <span className="suffix">%</span>
      </div>
      {hintText && <span className="field-hint">{hintText}</span>}
    </label>
  )
}

function PlainField({ label, value, onChange, hintText }: { label: string; value: string; onChange: (v: string) => void; hintText?: string }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input value={value} inputMode="decimal" onChange={(e) => onChange(e.target.value.replace(/[^0-9.-]/g, ''))} />
      {hintText && <span className="field-hint">{hintText}</span>}
    </label>
  )
}

function BucketRow({
  label, ret, alloc, onRet, onAlloc,
}: { label: string; ret: string; alloc: string; onRet: (v: string) => void; onAlloc: (v: string) => void }) {
  return (
    <div className="bucket-row">
      <span className="field-label" style={{ minWidth: 64 }}>{label}</span>
      <div className="field-suffix">
        <input value={ret} inputMode="decimal" onChange={(e) => onRet(e.target.value.replace(/[^0-9.-]/g, ''))} />
        <span className="suffix">% ret</span>
      </div>
      <div className="field-suffix">
        <input value={alloc} inputMode="decimal" onChange={(e) => onAlloc(e.target.value.replace(/[^0-9.]/g, ''))} />
        <span className="suffix">% wt</span>
      </div>
    </div>
  )
}

function AssumptionsSkeleton() {
  return (
    <div className="card">
      <div className="skel" style={{ height: 18, width: 200, marginBottom: 16 }} />
      <div className="grid-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skel" style={{ height: 180 }} />
        ))}
      </div>
    </div>
  )
}
