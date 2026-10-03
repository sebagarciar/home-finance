// Household profile: the one place for what the data can't tell — income,
// planned big expenses, an optional spending override, risk answers, and
// forecast settings. Spending, liquid cash and the current asset mix are
// derived from data (GET /assumptions/derived) and shown, not typed.
// The forecast and the Portfolio mix check both read from here.
import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  api, type Assumptions as Household, type AssumptionsUpdate, type PlannedExpense,
} from '../api/client'
import { useAssumptions, useAssumptionsDerived, useRiskProfile, useSpendingSummary } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { CURRENCIES } from '../lib/options'
import { MoneyField, Section } from '../components/fields'
import { RiskQuestions } from '../components/RiskQuestions'

interface Form {
  income1: string; income1ccy: string
  income2: string; income2ccy: string
  incomeGrowthPct: string; incomeSigma: string
  override: string; overrideCcy: string
  spendingGrowthPct: string
  planned: PlannedExpense[]
  retEquityPct: string; retBondsPct: string; retCashPct: string
  horizon: string; rho: string; inflationPct: string; fxDriftPct: string
}

const pct = (d: number) => String(Math.round(d * 1000) / 10) // 0.07 -> "7"
const num = (s: string) => (s.trim() === '' ? 0 : Number(s))
const nonZero = (s: string) => (Number(s) ? String(Number(s)) : '')

function seedForm(h: Household): Form {
  return {
    income1: nonZero(h.income_user1), income1ccy: h.income_user1_currency,
    income2: nonZero(h.income_user2), income2ccy: h.income_user2_currency,
    incomeGrowthPct: pct(h.income_growth_rate), incomeSigma: String(h.income_noise_sigma),
    override: h.spending_override_monthly != null ? String(Number(h.spending_override_monthly)) : '',
    overrideCcy: h.spending_override_currency,
    spendingGrowthPct: pct(h.spending_growth_rate),
    planned: h.planned_expenses.map((e) => ({ ...e, amount: String(Number(e.amount)) })),
    retEquityPct: pct(h.return_assumptions.equity ?? 0),
    retBondsPct: pct(h.return_assumptions.bonds ?? 0),
    retCashPct: pct(h.return_assumptions.cash ?? 0),
    horizon: String(h.horizon_years), rho: String(h.correlation_rho),
    inflationPct: pct(h.inflation_rate), fxDriftPct: pct(h.fx_drift_annual),
  }
}

export function Profile() {
  const householdQ = useAssumptions()
  const riskQ = useRiskProfile()
  if (!householdQ.data || riskQ.isLoading) return <ProfileSkeleton />
  return (
    <>
      <HouseholdForm initial={householdQ.data} />
      <RiskQuestions initial={riskQ.data?.profile ?? null} />
    </>
  )
}

function HouseholdForm({ initial }: { initial: Household }) {
  const qc = useQueryClient()
  const derivedQ = useAssumptionsDerived()
  const summaryQ = useSpendingSummary()
  const { format } = useCurrency()

  const [form, setForm] = useState<Form>(() => seedForm(initial))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const set = (patch: Partial<Form>) => {
    setForm((prev) => ({ ...prev, ...patch }))
    setSaved(false)
  }
  const setPlanned = (i: number, patch: Partial<PlannedExpense>) =>
    set({ planned: form.planned.map((e, j) => (j === i ? { ...e, ...patch } : e)) })

  // Income stays typed (it's irregular), with a hint from the Salary-category
  // inflows of recent complete months.
  const incomeHint = useMemo(() => {
    const rows = summaryQ.data?.by_month_income ?? []
    const running = new Date().toISOString().slice(0, 7)
    const recent = rows.filter((r) => r.month < running).slice(-6)
    if (recent.length === 0) return null
    return Math.round(recent.reduce((s, r) => s + Number(r.total), 0) / recent.length)
  }, [summaryQ.data])

  const derived = derivedQ.data
  const derivedSpend = derived?.spending.derived_monthly != null ? Number(derived.spending.derived_monthly) : null
  const usingOverride = form.override.trim() !== ''

  const save = async () => {
    setSaving(true)
    setErr(null)
    const payload: AssumptionsUpdate = {
      income_user1: form.income1 || '0', income_user1_currency: form.income1ccy,
      income_user2: form.income2 || '0', income_user2_currency: form.income2ccy,
      income_growth_rate: num(form.incomeGrowthPct) / 100,
      income_noise_sigma: num(form.incomeSigma),
      spending_override_monthly: usingOverride ? form.override.trim() : null,
      spending_override_currency: form.overrideCcy,
      spending_growth_rate: num(form.spendingGrowthPct) / 100,
      planned_expenses: form.planned.filter((e) => Number(e.amount) > 0 && /^\d{4}-\d{2}$/.test(e.month)),
      return_assumptions: {
        equity: num(form.retEquityPct) / 100,
        bonds: num(form.retBondsPct) / 100,
        cash: num(form.retCashPct) / 100,
      },
      horizon_years: Math.round(num(form.horizon)),
      correlation_rho: num(form.rho),
      inflation_rate: num(form.inflationPct) / 100,
      fx_drift_annual: num(form.fxDriftPct) / 100,
    }
    try {
      const updated = await api.assumptions.update(payload)
      setForm(seedForm(updated))
      // ['assumptions'] also covers the derived figures (effective spend moves).
      await Promise.all(
        [['assumptions'], ['forecast'], ['portfolio']].map((queryKey) => qc.invalidateQueries({ queryKey })),
      )
      setSaved(true)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Household profile</h2>
          <div className="card-meta">
            One place for what your data can&rsquo;t tell. The forecast and the portfolio check use it;
            spending, cash and your asset mix come from your statements and balances.
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

      <div className="profile-derived">
        <DerivedTile
          label="Monthly spending"
          value={derivedSpend != null ? format(derivedSpend) : '—'}
          sub={!derived
            ? 'loading…'
            : derived.spending.months.length
              ? `avg of ${monthRange(derived.spending.months)}`
              : 'import statements to derive it'}
        />
        <DerivedTile
          label="Liquid cash"
          value={derived ? format(Number(derived.liquid_cash)) : '—'}
          sub="bank balances + cash holdings"
        />
        <DerivedTile
          label="Current mix"
          value={derived ? mixLabel(derived.allocation) : '—'}
          sub="equity · bonds · cash, from today's net worth"
        />
      </div>

      <div className="grid-2">
        <Section title="Income" subtitle="Net monthly take-home for the household.">
          <MoneyField
            label="Monthly income"
            value={form.income1}
            ccy={form.income1ccy}
            onValue={(v) => set({ income1: v })}
            onCcy={(c) => set({ income1ccy: c })}
            hint={incomeHint != null
              ? { text: `use my avg (${incomeHint.toLocaleString('es-CL')} CLP)`,
                  onClick: () => set({ income1: String(incomeHint), income1ccy: 'CLP' }) }
              : undefined}
          />
          <MoneyField
            label="Second income (other currency, optional)"
            value={form.income2}
            ccy={form.income2ccy}
            onValue={(v) => set({ income2: v })}
            onCcy={(c) => set({ income2ccy: c })}
          />
          <PctField label="Annual income growth" value={form.incomeGrowthPct} onChange={(v) => set({ incomeGrowthPct: v })} />
        </Section>

        <Section
          title="Spending"
          subtitle={usingOverride
            ? 'Using your override instead of your statements.'
            : 'Using the average from your statements (shown above).'}
        >
          <MoneyField
            label="Override (leave empty to use statements)"
            value={form.override}
            ccy={form.overrideCcy}
            onValue={(v) => set({ override: v })}
            onCcy={(c) => set({ overrideCcy: c })}
            hint={usingOverride ? { text: 'use statements', onClick: () => set({ override: '' }) } : undefined}
          />
          <PctField label="Annual spending growth" value={form.spendingGrowthPct} onChange={(v) => set({ spendingGrowthPct: v })} />
        </Section>

        <Section
          title="Planned big expenses"
          subtitle="The forecast draws them down in their month; one within 2 years also makes a short-horizon target more cautious."
        >
          {form.planned.map((e, i) => (
            <div className="planned-row" key={i}>
              <input placeholder="What" value={e.label} maxLength={80}
                onChange={(ev) => setPlanned(i, { label: ev.target.value })} />
              <input placeholder="Amount" inputMode="decimal" value={e.amount}
                onChange={(ev) => setPlanned(i, { amount: ev.target.value.replace(/[^0-9.]/g, '') })} />
              <select value={e.currency} onChange={(ev) => setPlanned(i, { currency: ev.target.value })}>
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input type="month" value={e.month} aria-label="Month"
                onChange={(ev) => setPlanned(i, { month: ev.target.value })} />
              <button type="button" className="link-btn"
                onClick={() => set({ planned: form.planned.filter((_, j) => j !== i) })}>
                remove
              </button>
            </div>
          ))}
          <button type="button" className="link-btn" style={{ alignSelf: 'flex-start' }}
            onClick={() => set({ planned: [...form.planned, { label: '', amount: '', currency: 'EUR', month: nextMonth() }] })}>
            + add expense
          </button>
        </Section>

        <Section title="Forecast settings" subtitle="Expected returns and the stress levers. Defaults are fine for most uses.">
          <details className="profile-advanced">
            <summary>Show settings</summary>
            <div className="assumptions-fields">
              <PctField label="Equity return (annual)" value={form.retEquityPct} onChange={(v) => set({ retEquityPct: v })} />
              <PctField label="Bond return (annual)" value={form.retBondsPct} onChange={(v) => set({ retBondsPct: v })} />
              <PctField label="Cash return (annual)" value={form.retCashPct} onChange={(v) => set({ retCashPct: v })}
                hintText="Equity/bond returns are a fallback; the forecast samples real VT/AGG history when it can." />
              <PctField label="Inflation (annual)" value={form.inflationPct} onChange={(v) => set({ inflationPct: v })} />
              <PlainField label="Default horizon (years)" value={form.horizon} onChange={(v) => set({ horizon: v })} />
              <PlainField label="Correlation ρ (0–1)" value={form.rho} onChange={(v) => set({ rho: v })}
                hintText="How hard bad-market months hit income and spending. Default 0.3." />
              <PlainField label="Income noise σ (0–1)" value={form.incomeSigma} onChange={(v) => set({ incomeSigma: v })}
                hintText="Month-to-month income wobble. 0.05 is small." />
              <PctField label="CLP FX drift (annual)" value={form.fxDriftPct} onChange={(v) => set({ fxDriftPct: v })}
                hintText="0 = flat. Only affects foreign-currency income." />
            </div>
          </details>
        </Section>
      </div>
    </div>
  )
}

function DerivedTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="networth-tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value num">{value}</div>
      <div className="muted" style={{ fontSize: 12 }}>{sub}</div>
    </div>
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

function mixLabel(a: Record<string, number>): string {
  return ['equity', 'bonds', 'cash'].map((k) => `${Math.round((a[k] ?? 0) * 100)}%`).join(' · ')
}

// ["2026-04", …, "2026-09"] → "Apr–Sep 2026"
function monthRange(months: string[]): string {
  const fmt = (m: string, year: boolean) =>
    new Date(`${m}-01T00:00:00`).toLocaleString('en-US', year ? { month: 'short', year: 'numeric' } : { month: 'short' })
  const first = months[0]
  const last = months[months.length - 1]
  if (months.length === 1) return fmt(first, true)
  return first.slice(0, 4) === last.slice(0, 4) ? `${fmt(first, false)}–${fmt(last, true)}` : `${fmt(first, true)}–${fmt(last, true)}`
}

function nextMonth(): string {
  const d = new Date()
  d.setMonth(d.getMonth() + 1)
  return d.toISOString().slice(0, 7)
}

function ProfileSkeleton() {
  return (
    <div className="card">
      <div className="skel" style={{ height: 18, width: 200, marginBottom: 16 }} />
      <div className="grid-2">
        {[0, 1, 2, 3].map((i) => <div key={i} className="skel" style={{ height: 180 }} />)}
      </div>
    </div>
  )
}
