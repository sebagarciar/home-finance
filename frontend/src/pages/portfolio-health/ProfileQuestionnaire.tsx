import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type InvestorProfile, type ProfileInput } from '../../api/client'
import { useSpendingSummary } from '../../api/hooks'
import {
  CURRENCIES, GOALS, HORIZONS, KNOWLEDGE, LOSS, SCALE, STABILITY,
} from './constants'
import { MoneyField, Section, SelectField } from './fields'

interface FormState {
  primary_goal: string
  time_horizon: string
  risk_tolerance: string
  risk_capacity: string
  loss_reaction: string
  income_stability: string
  investment_knowledge: string
  monthly_income: string
  monthly_income_currency: string
  monthly_expenses: string
  monthly_expenses_currency: string
  emergency_fund_amount: string
  emergency_fund_currency: string
  tax_residence: string
  base_currency: string
  esg: boolean
  prefer_low_cost_index: boolean
  employer_stock_ticker: string
  max_crypto_pct: string
  notes: string
}

interface LargeExpense {
  label: string
  amount: string
  currency: string
  months_away: string
}

function seedForm(p: InvestorProfile | null): FormState {
  const c = (p?.constraints ?? {}) as Record<string, unknown>
  return {
    primary_goal: p?.primary_goal ?? 'long_term_growth',
    time_horizon: p?.time_horizon ?? '7_15y',
    risk_tolerance: p?.risk_tolerance ?? 'moderate',
    risk_capacity: p?.risk_capacity ?? 'moderate',
    loss_reaction: p?.loss_reaction ?? 'hold_uncomfortable',
    income_stability: p?.income_stability ?? 'stable',
    investment_knowledge: p?.investment_knowledge ?? 'intermediate',
    monthly_income: p ? String(Number(p.monthly_income)) : '',
    monthly_income_currency: p?.monthly_income_currency ?? 'CLP',
    monthly_expenses: p ? String(Number(p.monthly_expenses)) : '',
    monthly_expenses_currency: p?.monthly_expenses_currency ?? 'CLP',
    emergency_fund_amount: p ? String(Number(p.emergency_fund_amount)) : '',
    emergency_fund_currency: p?.emergency_fund_currency ?? 'CLP',
    tax_residence: p?.tax_residence ?? '',
    base_currency: p?.base_currency ?? 'CLP',
    esg: Boolean(c.esg),
    prefer_low_cost_index: Boolean(c.prefer_low_cost_index),
    employer_stock_ticker: (c.employer_stock_ticker as string) ?? '',
    max_crypto_pct: c.max_crypto_pct != null ? String(c.max_crypto_pct) : '',
    notes: (c.notes as string) ?? '',
  }
}

export function ProfileQuestionnaire({
  initial,
  onDone,
  onCancel,
}: {
  initial: InvestorProfile | null
  onDone: () => void
  onCancel?: () => void
}) {
  const qc = useQueryClient()
  const summaryQ = useSpendingSummary()
  const [form, setForm] = useState<FormState>(() => seedForm(initial))
  const [expenses, setExpenses] = useState<LargeExpense[]>(() =>
    (initial?.expected_large_expenses ?? []).map((e) => ({
      label: e.label, amount: String(e.amount), currency: e.currency, months_away: String(e.months_away),
    })),
  )
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const set = (patch: Partial<FormState>) => setForm((prev) => ({ ...prev, ...patch }))

  // "Use my avg" from the last ≤12 statemented months (same bridge as Assumptions).
  const suggestions = useMemo(() => {
    const s = summaryQ.data
    if (!s) return null
    const avg = (rows: { total: string }[]) => {
      const last = [...rows].slice(-12)
      if (last.length === 0) return null
      return Math.round(last.reduce((a, r) => a + Number(r.total), 0) / last.length)
    }
    return { spend: avg(s.by_month), income: avg(s.by_month_income) }
  }, [summaryQ.data])

  const save = async () => {
    setSaving(true)
    setErr(null)
    const constraints: Record<string, unknown> = {
      esg: form.esg,
      prefer_low_cost_index: form.prefer_low_cost_index,
      notes: form.notes,
    }
    if (form.employer_stock_ticker.trim()) constraints.employer_stock_ticker = form.employer_stock_ticker.trim().toUpperCase()
    if (form.max_crypto_pct.trim()) constraints.max_crypto_pct = Number(form.max_crypto_pct)

    const payload: ProfileInput = {
      primary_goal: form.primary_goal,
      time_horizon: form.time_horizon,
      risk_tolerance: form.risk_tolerance,
      risk_capacity: form.risk_capacity,
      loss_reaction: form.loss_reaction,
      income_stability: form.income_stability,
      investment_knowledge: form.investment_knowledge,
      monthly_income: form.monthly_income || '0',
      monthly_income_currency: form.monthly_income_currency,
      monthly_expenses: form.monthly_expenses || '0',
      monthly_expenses_currency: form.monthly_expenses_currency,
      emergency_fund_amount: form.emergency_fund_amount || '0',
      emergency_fund_currency: form.emergency_fund_currency,
      tax_residence: form.tax_residence.trim().toUpperCase().slice(0, 2),
      base_currency: form.base_currency,
      expected_large_expenses: expenses
        .filter((e) => e.amount.trim() !== '')
        .map((e) => ({
          label: e.label, amount: Number(e.amount), currency: e.currency, months_away: Number(e.months_away) || 0,
        })),
      constraints,
    }
    try {
      await api.portfolioHealth.putProfile(payload)
      await api.portfolioHealth.runReview() // generate a fresh review off the new profile
      await qc.invalidateQueries({ queryKey: ['portfolioHealth'] })
      onDone()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save profile')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Investor profile</h2>
          <div className="card-meta">
            We build an Investment Policy Profile from your answers, then evaluate your portfolio
            against it. This is an educational review — not investment, tax, or legal advice.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {onCancel && (
            <button className="btn" onClick={onCancel} disabled={saving}>Cancel</button>
          )}
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save & run review'}
          </button>
        </div>
      </div>
      {err && <div className="form-error" style={{ marginBottom: 12 }}>{err}</div>}

      <div className="grid-2">
        <Section title="Goals & horizon">
          <SelectField label="Primary investment goal" value={form.primary_goal}
            options={GOALS} onChange={(v) => set({ primary_goal: v })} />
          <SelectField label="Time horizon" value={form.time_horizon}
            options={HORIZONS} onChange={(v) => set({ time_horizon: v })} />
        </Section>

        <Section title="Risk">
          <SelectField label="Risk tolerance (comfort)" value={form.risk_tolerance}
            options={SCALE} onChange={(v) => set({ risk_tolerance: v })} />
          <SelectField label="Risk capacity (ability)" value={form.risk_capacity}
            options={SCALE} onChange={(v) => set({ risk_capacity: v })} />
          <SelectField label="Reaction to a market loss" value={form.loss_reaction}
            options={LOSS} onChange={(v) => set({ loss_reaction: v })} />
        </Section>

        <Section title="Cash flow" subtitle="Used for the liquidity & emergency-fund review.">
          <MoneyField label="Monthly income" value={form.monthly_income} ccy={form.monthly_income_currency}
            onValue={(v) => set({ monthly_income: v })} onCcy={(c) => set({ monthly_income_currency: c })}
            hint={suggestions?.income != null ? {
              text: `use my avg (${suggestions.income.toLocaleString('es-CL')} CLP)`,
              onClick: () => set({ monthly_income: String(suggestions.income), monthly_income_currency: 'CLP' }),
            } : undefined} />
          <MoneyField label="Monthly expenses" value={form.monthly_expenses} ccy={form.monthly_expenses_currency}
            onValue={(v) => set({ monthly_expenses: v })} onCcy={(c) => set({ monthly_expenses_currency: c })}
            hint={suggestions?.spend != null ? {
              text: `use my avg (${suggestions.spend.toLocaleString('es-CL')} CLP)`,
              onClick: () => set({ monthly_expenses: String(suggestions.spend), monthly_expenses_currency: 'CLP' }),
            } : undefined} />
          <MoneyField label="Emergency fund (cash set aside)" value={form.emergency_fund_amount}
            ccy={form.emergency_fund_currency} onValue={(v) => set({ emergency_fund_amount: v })}
            onCcy={(c) => set({ emergency_fund_currency: c })} />
        </Section>

        <Section title="Situation">
          <SelectField label="Income stability" value={form.income_stability}
            options={STABILITY} onChange={(v) => set({ income_stability: v })} />
          <SelectField label="Investment knowledge" value={form.investment_knowledge}
            options={KNOWLEDGE} onChange={(v) => set({ investment_knowledge: v })} />
          <label className="field">
            <span className="field-label">Tax residence (country code)</span>
            <input value={form.tax_residence} maxLength={2} placeholder="CL"
              onChange={(e) => set({ tax_residence: e.target.value.replace(/[^a-zA-Z]/g, '') })} />
          </label>
          <SelectField label="Base currency" value={form.base_currency}
            options={CURRENCIES.map((c) => [c, c] as const)} onChange={(v) => set({ base_currency: v })} />
        </Section>

        <Section title="Constraints" subtitle="Optional preferences that tighten policy limits.">
          <label className="field phr-check">
            <input type="checkbox" checked={form.esg} onChange={(e) => set({ esg: e.target.checked })} />
            <span className="field-label" style={{ marginBottom: 0 }}>ESG preference</span>
          </label>
          <label className="field phr-check">
            <input type="checkbox" checked={form.prefer_low_cost_index}
              onChange={(e) => set({ prefer_low_cost_index: e.target.checked })} />
            <span className="field-label" style={{ marginBottom: 0 }}>Prefer low-cost index funds</span>
          </label>
          <label className="field">
            <span className="field-label">Employer stock ticker</span>
            <input value={form.employer_stock_ticker} placeholder="e.g. ACME"
              onChange={(e) => set({ employer_stock_ticker: e.target.value })} />
          </label>
          <label className="field">
            <span className="field-label">Max crypto allocation (%)</span>
            <input value={form.max_crypto_pct} inputMode="decimal" placeholder="optional"
              onChange={(e) => set({ max_crypto_pct: e.target.value.replace(/[^0-9.]/g, '') })} />
          </label>
        </Section>

        <Section title="Large expenses (next 24 months)" subtitle="Raises your liquidity target.">
          {expenses.map((e, i) => (
            <div className="phr-expense-row" key={i}>
              <input placeholder="Label" value={e.label}
                onChange={(ev) => setExpenses((xs) => patchRow(xs, i, { label: ev.target.value }))} />
              <input placeholder="Amount" inputMode="decimal" value={e.amount}
                onChange={(ev) => setExpenses((xs) => patchRow(xs, i, { amount: ev.target.value.replace(/[^0-9.]/g, '') }))} />
              <select value={e.currency}
                onChange={(ev) => setExpenses((xs) => patchRow(xs, i, { currency: ev.target.value }))}>
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input placeholder="Months" inputMode="numeric" value={e.months_away} title="Months away"
                onChange={(ev) => setExpenses((xs) => patchRow(xs, i, { months_away: ev.target.value.replace(/[^0-9]/g, '') }))} />
              <button type="button" className="link-btn" onClick={() => setExpenses((xs) => xs.filter((_, j) => j !== i))}>
                remove
              </button>
            </div>
          ))}
          <button type="button" className="link-btn"
            onClick={() => setExpenses((xs) => [...xs, { label: '', amount: '', currency: 'CLP', months_away: '' }])}>
            + add expense
          </button>
        </Section>
      </div>
    </div>
  )
}

function patchRow(rows: LargeExpense[], i: number, patch: Partial<LargeExpense>): LargeExpense[] {
  return rows.map((r, j) => (j === i ? { ...r, ...patch } : r))
}
