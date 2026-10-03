// Cost-basis ledger for one holding: list, add, edit, delete trades.
// Holding.quantity stays the source of truth for units; the ledger only
// supplies basis, so the header shows whether the two reconcile.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  api, type Holding, type HoldingPerformance, type Trade, type TradeInput, type TradeKind,
} from '../api/client'
import { queryKeys, useTrades } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { fmtNative, fmtPct, fmtQty, shortDate } from '../lib/format'
import { ISSUE_TEXT } from '../lib/performance'

const UNIT_KINDS: TradeKind[] = ['opening', 'buy', 'sell']
const KIND_LABEL: Record<TradeKind, string> = {
  opening: 'Starting position',
  buy: 'Buy',
  sell: 'Sell',
  dividend: 'Dividend',
  fee: 'Fee',
}

type Mode = 'qty' | 'amount'

interface FormState {
  kind: TradeKind
  date: string
  mode: Mode
  quantity: string
  amount: string
  price: string
  fees: string
  note: string
}

const today = () => new Date().toISOString().slice(0, 10)

function blankForm(holding: Holding, trades: Trade[]): FormState {
  const empty = trades.length === 0
  return {
    kind: empty ? 'opening' : 'buy',
    date: today(),
    mode: 'qty',
    // An empty ledger usually starts from "what I hold now", which reconciles immediately.
    quantity: empty ? String(Number(holding.quantity)) : '',
    amount: '',
    price: '',
    fees: '',
    note: '',
  }
}

function formFromTrade(t: Trade): FormState {
  const unit = UNIT_KINDS.includes(t.kind)
  return {
    kind: t.kind,
    date: t.date,
    mode: unit ? 'qty' : 'amount',
    quantity: unit ? String(Number(t.quantity)) : '',
    amount: unit ? '' : String(Number(t.amount)),
    price: unit ? String(Number(t.price)) : '',
    fees: Number(t.fees) ? String(Number(t.fees)) : '',
    note: t.note ?? '',
  }
}

function toPayload(f: FormState): TradeInput {
  const note = f.note.trim() || null
  if (!UNIT_KINDS.includes(f.kind)) {
    return { date: f.date, kind: f.kind, amount: f.amount.trim(), quantity: null, price: null, fees: '0', note }
  }
  return {
    date: f.date,
    kind: f.kind,
    price: f.price.trim(),
    quantity: f.mode === 'qty' ? f.quantity.trim() : null,
    amount: f.mode === 'amount' ? f.amount.trim() : null,
    fees: f.fees.trim() || '0',
    note,
  }
}

export function TradesModal({
  holding, perf, onClose,
}: {
  holding: Holding
  perf: HoldingPerformance | undefined
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { format, mask } = useCurrency()
  const tradesQ = useTrades(holding.id)
  const trades = tradesQ.data ?? []
  const ccy = holding.price_currency

  const [editing, setEditing] = useState<Trade | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form opens once trades have loaded so the defaults know whether the ledger is empty.
  const f = form ?? (tradesQ.isSuccess ? blankForm(holding, trades) : null)
  const set = (patch: Partial<FormState>) => f && setForm({ ...f, ...patch })

  const hasOpening = trades.some((t) => t.kind === 'opening' && t.id !== editing?.id)
  const kinds = (Object.keys(KIND_LABEL) as TradeKind[]).filter((k) => k !== 'opening' || !hasOpening)

  // Performance re-prices every holding, so it can be slow; don't hold the form on it.
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.performance() })
    return qc.invalidateQueries({ queryKey: queryKeys.trades(holding.id) })
  }

  const reset = () => {
    setEditing(null)
    setForm(null)
    setError(null)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!f) return
    setSaving(true)
    setError(null)
    try {
      const payload = toPayload(f)
      if (editing) await api.trades.update(editing.id, payload)
      else await api.trades.create(holding.id, payload)
      reset()
      await refresh()
    } catch (err) {
      setError(apiMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (t: Trade) => {
    if (!confirm(`Delete this ${KIND_LABEL[t.kind].toLowerCase()} from ${t.date}?`)) return
    setError(null)
    try {
      await api.trades.remove(t.id)
      if (editing?.id === t.id) reset()
      await refresh()
    } catch (err) {
      setError(apiMessage(err))
    }
  }

  const unit = f ? UNIT_KINDS.includes(f.kind) : true

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <h3>Cost basis · {holding.ticker}</h3>
          <button className="link-btn" onClick={onClose}>close</button>
        </div>

        <BasisSummary holding={holding} perf={perf} format={format} mask={mask} />

        {trades.length > 0 && (
          <div className="ledger-table">
            <div className="ledger-head">
              <span>Date</span>
              <span>Kind</span>
              <span className="num-col">Units</span>
              <span className="num-col">Price</span>
              <span className="num-col">Cash</span>
              <span />
            </div>
            {trades.map((t) => {
              const isUnit = UNIT_KINDS.includes(t.kind)
              const cash = isUnit ? Number(t.quantity) * Number(t.price) : Number(t.amount)
              return (
                <div key={t.id} className={`ledger-row${editing?.id === t.id ? ' active' : ''}`}>
                  <span>{shortDate(t.date)} <span className="muted">{t.date.slice(0, 4)}</span></span>
                  <span>
                    {KIND_LABEL[t.kind]}
                    {t.note && <span className="muted" style={{ display: 'block', fontSize: 11 }}>{t.note}</span>}
                  </span>
                  <span className="num num-col">{isUnit ? mask(fmtQty(t.quantity)) : '—'}</span>
                  <span className="num num-col">{isUnit ? mask(fmtNative(t.price, ccy)) : '—'}</span>
                  <span className="num num-col num-stack">
                    <span>{mask(fmtNative(String(cash), ccy))}</span>
                    {Number(t.fees) > 0 && (
                      <span className="muted" style={{ fontSize: 11 }}>fees {mask(fmtNative(t.fees, ccy))}</span>
                    )}
                  </span>
                  <span className="holding-actions">
                    <button className="link-btn" onClick={() => { setEditing(t); setForm(formFromTrade(t)); setError(null) }}>
                      edit
                    </button>
                    <button className="link-btn danger" onClick={() => remove(t)}>delete</button>
                  </span>
                </div>
              )
            })}
          </div>
        )}

        {f && (
          <form className="trade-form" onSubmit={submit}>
            <div className="trade-form-title">
              {editing ? `Edit ${KIND_LABEL[editing.kind].toLowerCase()}` : trades.length === 0 ? 'Set starting position' : 'Add trade'}
            </div>
            <label className="modal-field">
              Kind
              <select value={f.kind} onChange={(e) => set({ kind: e.target.value as TradeKind })}>
                {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>
            </label>
            <label className="modal-field">
              Date
              <input type="date" value={f.date} max={today()} onChange={(e) => set({ date: e.target.value })} required />
            </label>
            {unit ? (
              <>
                <label className="modal-field">
                  <span className="mode-switch">
                    {(['qty', 'amount'] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        className={f.mode === m ? 'active' : ''}
                        onClick={() => set({ mode: m })}
                      >
                        {m === 'qty' ? 'Units' : `Cash (${ccy})`}
                      </button>
                    ))}
                  </span>
                  {f.mode === 'qty' ? (
                    <input inputMode="decimal" value={f.quantity} onChange={(e) => set({ quantity: e.target.value })} required />
                  ) : (
                    <input
                      inputMode="decimal"
                      value={f.amount}
                      onChange={(e) => set({ amount: e.target.value })}
                      placeholder={f.kind === 'sell' ? 'net proceeds' : 'cash paid'}
                      required
                    />
                  )}
                </label>
                <label className="modal-field">
                  {f.kind === 'opening' ? `Avg cost / unit (${ccy})` : `Price / unit (${ccy})`}
                  <input inputMode="decimal" value={f.price} onChange={(e) => set({ price: e.target.value })} required />
                </label>
                <label className="modal-field">
                  Fees ({ccy})
                  <input inputMode="decimal" value={f.fees} onChange={(e) => set({ fees: e.target.value })} placeholder="0" />
                </label>
              </>
            ) : (
              <label className="modal-field">
                Amount ({ccy})
                <input inputMode="decimal" value={f.amount} onChange={(e) => set({ amount: e.target.value })} required />
              </label>
            )}
            <label className="modal-field trade-note">
              Note
              <input value={f.note} maxLength={255} onChange={(e) => set({ note: e.target.value })} />
            </label>
            {error && <div className="form-error">{error}</div>}
            <div className="modal-actions trade-actions">
              {editing && <button type="button" className="btn" onClick={reset} disabled={saving}>Cancel edit</button>}
              <button className="btn primary" disabled={saving}>
                {saving ? 'Saving…' : editing ? 'Save' : 'Add'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

function BasisSummary({
  holding, perf, format, mask,
}: {
  holding: Holding
  perf: HoldingPerformance | undefined
  format: (n: number) => string
  mask: (s: string) => string
}) {
  if (!perf) return null
  const ccy = holding.price_currency
  const issue = perf.issue && perf.issue !== 'no_trades' ? perf.issue : null
  return (
    <div className="basis-summary">
      <div className="basis-stats">
        <Stat label="Units" value={
          perf.has_basis
            ? `${mask(fmtQty(perf.ledger_qty))} / ${mask(fmtQty(perf.holding_qty))}`
            : mask(fmtQty(perf.holding_qty))
        } sub={perf.has_basis ? 'ledger / holding' : 'holding'} />
        <Stat
          label="Avg cost"
          value={perf.avg_cost_native ? mask(fmtNative(perf.avg_cost_native, ccy)) : '—'}
        />
        <Stat label="Invested" value={perf.has_basis ? format(Number(perf.cost_base)) : '—'} />
        <Stat
          label="Unrealized"
          value={perf.unrealized_base != null ? format(Number(perf.unrealized_base)) : '—'}
          tone={perf.unrealized_base != null ? Math.sign(Number(perf.unrealized_base)) : 0}
          sub={perf.price_effect != null && perf.fx_effect != null
            ? `asset ${format(Number(perf.price_effect))} · FX ${format(Number(perf.fx_effect))}`
            : undefined}
        />
        <Stat
          label="Return"
          value={perf.return != null ? fmtPct(perf.return) : '—'}
          tone={perf.return != null ? Math.sign(perf.return) : 0}
          sub={perf.return != null
            ? `${perf.annualized ? 'per year' : 'total'}${perf.return_native != null && ccy !== 'CLP' ? ` · ${fmtPct(perf.return_native)} in ${ccy}` : ''}`
            : undefined}
        />
      </div>
      {perf.issue && (
        <div className={issue ? 'basis-issue warn' : 'basis-issue'}>{ISSUE_TEXT[perf.issue]}</div>
      )}
    </div>
  )
}

function Stat({ label, value, sub, tone = 0 }: { label: string; value: string; sub?: string; tone?: number }) {
  const color = tone > 0 ? 'var(--positive-text)' : tone < 0 ? 'var(--negative-text)' : undefined
  return (
    <div className="basis-stat">
      <div className="tile-label">{label}</div>
      <div className="num" style={{ fontWeight: 600, color }}>{value}</div>
      {sub && <div className="muted" style={{ fontSize: 11 }}>{sub}</div>}
    </div>
  )
}

// request() throws "API 422: {json}". Surface FastAPI's `detail` when present.
function apiMessage(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err)
  const m = /^API \d+: (.*)$/s.exec(msg)
  if (!m) return msg
  try {
    const detail = JSON.parse(m[1]).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d) => d.msg ?? String(d)).join('; ')
  } catch {
    // not JSON — fall through
  }
  return m[1]
}
