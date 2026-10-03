// Forecast goals: "have X by a month", each with the chance the simulation
// gives it. The headline of the Forecast page. Goals are stored on the
// household profile (PUT /assumptions { goals }) and edited inline here.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type Goal, type GoalResult } from '../api/client'
import { useAssumptions } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { fmtNative } from '../lib/format'
import { monthLabel, probColor } from '../lib/goals'
import { CURRENCIES } from '../lib/options'

const goalKey = (g: Goal) => `${g.month}|${g.label}|${Number(g.amount)}|${g.currency}`

export function Goals({ results, real }: { results: GoalResult[]; real: boolean }) {
  const qc = useQueryClient()
  const householdQ = useAssumptions()
  const goals = householdQ.data?.goals ?? []
  const byKey = new Map(results.map((r) => [goalKey(r), r]))

  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const save = async (next: Goal[]) => {
    setErr(null)
    try {
      await api.assumptions.update({ goals: next })
      setEditing(null)
      await Promise.all([['assumptions'], ['forecast']].map((queryKey) => qc.invalidateQueries({ queryKey })))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save goal')
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Goals</h2>
          <div className="card-meta">
            How likely you are to have each amount by its date{real ? ', in today’s money' : ''}.
            If you&rsquo;ll actually spend it, also add it as a planned expense in your Profile.
          </div>
        </div>
        {editing !== 'new' && (
          <button className="btn" onClick={() => setEditing('new')}>+ Add goal</button>
        )}
      </div>
      {err && <div className="form-error" style={{ marginBottom: 12 }}>{err}</div>}

      {goals.length === 0 && editing !== 'new' && (
        <div className="empty">
          No goals yet. Add one, like a €15k deposit by mid-2028, to see how likely it is.
        </div>
      )}

      <div className="goal-list">
        {goals.map((g, i) =>
          editing === i ? (
            <GoalForm
              key={goalKey(g)}
              initial={g}
              onCancel={() => setEditing(null)}
              onSave={(edited) => save(goals.map((x, j) => (j === i ? edited : x)))}
              onDelete={() => save(goals.filter((_, j) => j !== i))}
            />
          ) : (
            <GoalTile key={goalKey(g)} goal={g} result={byKey.get(goalKey(g))} onEdit={() => setEditing(i)} />
          ),
        )}
        {editing === 'new' && (
          <GoalForm onCancel={() => setEditing(null)} onSave={(g) => save([...goals, g])} />
        )}
      </div>
    </div>
  )
}

function GoalTile({ goal, result, onEdit }: { goal: Goal; result: GoalResult | undefined; onEdit: () => void }) {
  const { format, mask } = useCurrency()
  const p = result?.probability ?? null
  const past = result != null && result.months_away < 0
  return (
    <button className="goal-tile" onClick={onEdit} title="Edit goal">
      <div className="goal-head">
        <span className="goal-label">{goal.label || 'Goal'}</span>
        <span className="muted">{mask(fmtNative(goal.amount, goal.currency))} by {monthLabel(goal.month)}</span>
      </div>
      <div className="goal-prob num" style={{ color: probColor(p) }}>
        {past ? 'Past' : p == null ? '…' : `${Math.round(p * 100)}%`}
        {!past && p != null && <span className="goal-prob-sub">likely</span>}
      </div>
      <div className="muted goal-foot">
        {past
          ? 'This date has passed: edit or remove it.'
          : result?.p50 != null
            ? `Median then ${format(result.p50)} · pessimistic ${format(result.p10 ?? 0)}`
            : 'Running the forecast…'}
      </div>
    </button>
  )
}

function GoalForm({
  initial, onSave, onCancel, onDelete,
}: {
  initial?: Goal
  onSave: (g: Goal) => void
  onCancel: () => void
  onDelete?: () => void
}) {
  const [label, setLabel] = useState(initial?.label ?? '')
  const [amount, setAmount] = useState(initial ? String(Number(initial.amount)) : '')
  const [currency, setCurrency] = useState(initial?.currency ?? 'EUR')
  const [month, setMonth] = useState(initial?.month ?? defaultMonth())
  const valid = Number(amount) > 0 && /^\d{4}-\d{2}$/.test(month)

  return (
    <form
      className="goal-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid) onSave({ label: label.trim(), amount, currency, month })
      }}
    >
      <input placeholder="What for (e.g. Deposit)" value={label} maxLength={80}
        onChange={(e) => setLabel(e.target.value)} aria-label="Goal name" />
      <input placeholder="Amount" inputMode="decimal" value={amount} aria-label="Amount"
        onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ''))} />
      <select value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
        {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="By month" />
      <span className="goal-form-actions">
        {onDelete && <button type="button" className="link-btn danger" onClick={onDelete}>delete</button>}
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={!valid}>Save</button>
      </span>
    </form>
  )
}

function defaultMonth(): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() + 2)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
