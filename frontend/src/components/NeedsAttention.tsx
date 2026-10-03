// "Needs attention": computed signals that the numbers on this page have gone
// stale (GET /attention). Each row carries its own fix: update a balance or
// price in place, archive a transfer pair, or jump to Import / Transactions.
// Renders nothing when everything is current.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type AttentionItem } from '../api/client'
import { queryKeys, useAttention } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { fmtNative, shortDate } from '../lib/format'
import { useNav } from '../lib/nav'

type Of<K extends AttentionItem['kind']> = Extract<AttentionItem, { kind: K }>

export function NeedsAttention() {
  const qc = useQueryClient()
  const q = useAttention()
  const [restoring, setRestoring] = useState(false)
  const data = q.data
  if (!data || data.items.length === 0) return null

  const refresh = (...keys: (readonly unknown[])[]) =>
    Promise.all([queryKeys.attention(), ...keys].map((queryKey) => qc.invalidateQueries({ queryKey })))
  const dismiss = async (...keys: string[]) => {
    await Promise.all(keys.map((k) => api.attention.dismiss(k)))
    await refresh()
  }

  // Missing statements are listed per month but read better per account.
  const statements = new Map<number, Of<'statement_missing'>[]>()
  for (const i of data.items) {
    if (i.kind === 'statement_missing') {
      statements.set(i.account_id, [...(statements.get(i.account_id) ?? []), i])
    }
  }

  return (
    <div className="card attention-card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Needs attention</h2>
          <div className="card-meta">Fix these and the numbers below stay trustworthy</div>
        </div>
        <span className="attention-count">
          {data.items.filter((i) => i.kind !== 'statement_missing').length + statements.size}
        </span>
      </div>
      <div className="attention-list">
        {data.items.map((item) => {
          switch (item.kind) {
            case 'stale_balance':
              return <StaleBalance key={item.key} item={item} refresh={refresh} dismiss={dismiss} />
            case 'statement_missing': {
              const group = statements.get(item.account_id) ?? []
              // Render the group once, at its first month.
              if (group[0]?.key !== item.key) return null
              return <MissingStatements key={item.key} items={group} dismiss={dismiss} />
            }
            case 'transfer_pair':
              return <TransferPair key={item.key} item={item} refresh={refresh} dismiss={dismiss} />
            case 'uncategorized':
              return <Uncategorized key={item.key} item={item} dismiss={dismiss} />
            case 'stale_price':
              return <StalePrice key={item.key} item={item} refresh={refresh} dismiss={dismiss} />
          }
        })}
      </div>
      {data.dismissed > 0 && (
        <div className="attention-footer muted">
          Some items are dismissed ·{' '}
          <button
            className="link-btn"
            disabled={restoring}
            onClick={async () => {
              setRestoring(true)
              try {
                await api.attention.restoreAll()
                await refresh()
              } finally {
                setRestoring(false)
              }
            }}
          >
            show them again
          </button>
        </div>
      )}
    </div>
  )
}

type Refresh = (...keys: (readonly unknown[])[]) => Promise<unknown>
type Dismiss = (...keys: string[]) => Promise<void>

function Row({
  title, detail, children, onDismiss, dismissLabel = 'dismiss',
}: {
  title: React.ReactNode
  detail?: React.ReactNode
  children?: React.ReactNode
  onDismiss: () => void
  dismissLabel?: string
}) {
  return (
    <div className="attention-row">
      <div className="attention-text">
        <div className="attention-title">{title}</div>
        {detail && <div className="attention-detail">{detail}</div>}
      </div>
      <div className="attention-actions">
        {children}
        <button className="link-btn" onClick={onDismiss}>{dismissLabel}</button>
      </div>
    </div>
  )
}

// Inline "type a number, save" used by balances and prices.
function InlineAmount({
  currency, placeholder, onSave,
}: {
  currency: string
  placeholder: string
  onSave: (value: string) => Promise<unknown>
}) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <form
      className="attention-inline"
      onSubmit={async (e) => {
        e.preventDefault()
        if (!value.trim()) return
        setSaving(true)
        setError(null)
        try {
          await onSave(value.trim())
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err))
          setSaving(false)
        }
      }}
    >
      <input
        inputMode="decimal"
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        aria-label={`New amount in ${currency}`}
      />
      <span className="muted">{currency}</span>
      <button className="btn" disabled={saving || !value.trim()}>{saving ? 'Saving…' : 'Update'}</button>
      {error && <span className="form-error">{error}</span>}
    </form>
  )
}

function StaleBalance({ item, refresh, dismiss }: { item: Of<'stale_balance'>; refresh: Refresh; dismiss: Dismiss }) {
  const { mask } = useCurrency()
  return (
    <Row
      title={<><strong>{item.account_name}</strong> balance is out of date</>}
      detail={item.updated_on
        ? `Last updated ${item.age_days} days ago (${mask(fmtNative(item.current_balance, item.currency))}). Net worth and runway use it.`
        : 'Never set. Net worth and runway use it.'}
      onDismiss={() => dismiss(item.key)}
    >
      <InlineAmount
        currency={item.currency}
        placeholder={mask(String(Number(item.current_balance)))}
        onSave={async (v) => {
          await api.accounts.setBalance(item.account_id, v)
          await refresh(['networth'], ['accounts'])
        }}
      />
    </Row>
  )
}

function MissingStatements({ items, dismiss }: { items: Of<'statement_missing'>[]; dismiss: Dismiss }) {
  const { go } = useNav()
  const first = items[0]
  const months = monthList(items.map((i) => i.month))
  const rows = items.reduce((n, i) => n + i.email_rows, 0)
  return (
    <Row
      title={<><strong>{first.account_name}</strong>: no statement for {months}</>}
      detail={`${rows} rows there are provisional email notifications (authorized amounts, sometimes partial). Importing the statement replaces them.`}
      onDismiss={() => dismiss(...items.map((i) => i.key))}
    >
      <button className="btn" onClick={() => go('transactions', { view: 'import', accountId: first.account_id })}>
        Import statement
      </button>
    </Row>
  )
}

function TransferPair({ item, refresh, dismiss }: { item: Of<'transfer_pair'>; refresh: Refresh; dismiss: Dismiss }) {
  const { mask } = useCurrency()
  const [busy, setBusy] = useState(false)
  return (
    <Row
      title={<>Possible transfer: <strong>{item.out.account_name}</strong> → <strong>{item.in.account_name}</strong>,{' '}
        <span className="num">{mask(fmtNative(item.amount, item.currency))}</span></>}
      detail={`${shortDate(item.out.date)} “${item.out.description}” · ${shortDate(item.in.date)} “${item.in.description}”. Counted as spending until archived.`}
      onDismiss={() => dismiss(item.key)}
      dismissLabel="not a transfer"
    >
      <button
        className="btn"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          try {
            await Promise.all([api.transactions.archive(item.out.id), api.transactions.archive(item.in.id)])
            await refresh(['transactions'], ['spending'])
          } finally {
            setBusy(false)
          }
        }}
      >
        {busy ? 'Archiving…' : 'Archive both'}
      </button>
    </Row>
  )
}

function Uncategorized({ item, dismiss }: { item: Of<'uncategorized'>; dismiss: Dismiss }) {
  const { go } = useNav()
  return (
    <Row
      title={<><strong>{item.count}</strong> {item.count === 1 ? 'transaction' : 'transactions'} in {item.category}</>}
      detail={`Since ${shortDate(item.since)}. Categorizing one teaches the rule for every row from that merchant.`}
      onDismiss={() => dismiss(item.key)}
    >
      <button className="btn" onClick={() => go('transactions', { category: item.category, start: item.since })}>
        Review
      </button>
    </Row>
  )
}

function StalePrice({ item, refresh, dismiss }: { item: Of<'stale_price'>; refresh: Refresh; dismiss: Dismiss }) {
  const { mask } = useCurrency()
  return (
    <Row
      title={<><strong>{item.ticker}</strong> has no recent price</>}
      detail={item.last_priced_on
        ? `Last priced ${shortDate(item.last_priced_on)}${item.manual_price ? ` (manual ${mask(fmtNative(item.manual_price, item.currency))})` : ''}. Enter today's price, or check the ticker.`
        : 'Never priced, so it counts as zero in net worth. Enter a manual price, or check the ticker.'}
      onDismiss={() => dismiss(item.key)}
    >
      <InlineAmount
        currency={item.currency}
        placeholder="price"
        onSave={async (v) => {
          await api.holdings.setManualPrice(item.holding_id, v)
          await refresh(['holdings'], ['networth'], ['performance'])
        }}
      />
    </Row>
  )
}

// ["2026-06", "2026-07", "2026-09"] → "Jun, Jul and Sep 2026" (year shown once
// when shared, per month otherwise).
function monthList(yms: string[]): string {
  const sameYear = new Set(yms.map((m) => m.slice(0, 4))).size === 1
  const labels = yms.map((m) =>
    new Date(`${m}-01T00:00:00`).toLocaleString('en-US', sameYear ? { month: 'short' } : { month: 'short', year: 'numeric' }),
  )
  const list = labels.length <= 1
    ? (labels[0] ?? '')
    : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
  return sameYear ? `${list} ${yms[0].slice(0, 4)}` : list
}
