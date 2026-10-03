// Risk & goal answers (Forecast → Profile). Money isn't asked here: income,
// spending, cash and planned expenses live in the household profile or come
// from the data. Saving writes a new profile version; the Health Review uses
// the latest one on its next run.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type InvestorProfile, type ProfileInput } from '../../api/client'
import {
  CURRENCIES, GOALS, HORIZONS, KNOWLEDGE, LOSS, SCALE, STABILITY,
} from './constants'
import { Section, SelectField } from './fields'

interface FormState {
  primary_goal: string
  time_horizon: string
  risk_tolerance: string
  risk_capacity: string
  loss_reaction: string
  income_stability: string
  investment_knowledge: string
  tax_residence: string
  base_currency: string
  esg: boolean
  prefer_low_cost_index: boolean
  employer_stock_ticker: string
  max_crypto_pct: string
  notes: string
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
    tax_residence: p?.tax_residence ?? '',
    base_currency: p?.base_currency ?? 'CLP',
    esg: Boolean(c.esg),
    prefer_low_cost_index: Boolean(c.prefer_low_cost_index),
    employer_stock_ticker: (c.employer_stock_ticker as string) ?? '',
    max_crypto_pct: c.max_crypto_pct != null ? String(c.max_crypto_pct) : '',
    notes: (c.notes as string) ?? '',
  }
}

export function ProfileQuestionnaire({ initial }: { initial: InvestorProfile | null }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<FormState>(() => seedForm(initial))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const set = (patch: Partial<FormState>) => {
    setForm((prev) => ({ ...prev, ...patch }))
    setSaved(false)
  }

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
      tax_residence: form.tax_residence.trim().toUpperCase().slice(0, 2),
      base_currency: form.base_currency,
      constraints,
    }
    try {
      await api.portfolioHealth.putProfile(payload)
      await qc.invalidateQueries({ queryKey: ['portfolioHealth'] })
      setSaved(true)
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
          <h2 className="card-title">Risk &amp; goals</h2>
          <div className="card-meta">
            Sets the target mix and limits the Health Review checks your portfolio against.
            Educational only, not investment, tax or legal advice.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {saved && <span className="tag tag-info">Saved ✓</span>}
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save answers'}
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

      </div>
    </div>
  )
}
