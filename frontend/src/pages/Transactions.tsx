import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type Account, type Category, type Transaction, type TxnType } from '../api/client'
import { useCurrency } from '../lib/currency'
import { useTransactions, useCategories, useAccounts } from '../api/hooks'
import { categoryStyle, categoryColorHex } from '../design/categories'
import { Import } from './Import'

type SortKey = 'date_desc' | 'date_asc' | 'amount_desc' | 'amount_asc'
type View = 'transactions' | 'import'

export function Transactions() {
  const [view, setView] = useState<View>('transactions')
  return (
    <>
      <div className="subtabs">
        {(['transactions', 'import'] as const).map((v) => (
          <button
            key={v}
            className={`subtab${view === v ? ' active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'transactions' ? 'Transactions' : 'Import'}
          </button>
        ))}
      </div>
      {view === 'transactions' ? <TransactionsView /> : <Import />}
    </>
  )
}

function TransactionsView() {
  const { format } = useCurrency()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [category, setCategory] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sort, setSort] = useState<SortKey>('date_desc')
  const [showArchived, setShowArchived] = useState(false)
  const [editing, setEditing] = useState<Transaction | null>(null)
  const [creating, setCreating] = useState(false)

  // Debounce the search box into the query key so typing doesn't fire a request
  // per keystroke; TanStack Query dedupes + caches the rest.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 200)
    return () => clearTimeout(t)
  }, [search])

  const txnsQ = useTransactions({
    search: debouncedSearch || undefined,
    category: category || undefined,
    start: dateFrom || undefined,
    end: dateTo || undefined,
    include_archived: showArchived || undefined,
  })
  const txns = useMemo(() => txnsQ.data ?? [], [txnsQ.data])
  const categories = useCategories().data ?? []
  const accounts = useAccounts().data ?? []
  const loading = txnsQ.isLoading
  const reload = () => qc.invalidateQueries({ queryKey: ['transactions'] })

  const sorted = useMemo(() => {
    const arr = [...txns]
    switch (sort) {
      case 'date_asc':
        arr.sort((a, b) => a.date.localeCompare(b.date))
        break
      case 'amount_desc':
        arr.sort((a, b) => Math.abs(Number(b.amount_in_base)) - Math.abs(Number(a.amount_in_base)))
        break
      case 'amount_asc':
        arr.sort((a, b) => Math.abs(Number(a.amount_in_base)) - Math.abs(Number(b.amount_in_base)))
        break
      default:
        arr.sort((a, b) => b.date.localeCompare(a.date))
    }
    return arr
  }, [txns, sort])

  const groupedByDate = useMemo(() => groupByDate(sorted), [sorted])
  const groupingByDate = sort === 'date_desc' || sort === 'date_asc'

  return (
    <>
      <div className="card" style={{ padding: '14px 18px' }}>
        <div className="filters">
          <label>
            Search
            <input
              type="search"
              placeholder="Merchant or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ minWidth: 220 }}
            />
          </label>
          <label>
            Category
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All</option>
              {categories.map((c) => (
                <option key={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <label>
            From
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              style={{ minWidth: 130 }}
            />
          </label>
          <label>
            To
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              style={{ minWidth: 130 }}
            />
          </label>
          <label>
            Sort
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="date_desc">Date · newest first</option>
              <option value="date_asc">Date · oldest first</option>
              <option value="amount_desc">Amount · highest first</option>
              <option value="amount_asc">Amount · lowest first</option>
            </select>
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6, textTransform: 'none', letterSpacing: 0, fontSize: 12, color: 'var(--text-secondary)' }}>
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              style={{ width: 'auto', padding: 0 }}
            />
            Show archived
          </label>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              {loading ? 'Loading…' : `${txns.length} transactions`}
            </span>
            <button className="btn primary" onClick={() => setCreating(true)}>
              + Add
            </button>
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 12 }}>
        {loading ? (
          <SkeletonRows />
        ) : sorted.length === 0 ? (
          <div className="empty">No transactions. Import a bank statement or add one manually.</div>
        ) : groupingByDate ? (
          <div className="txn-list">
            {groupedByDate.map(([date, rows]) => (
              <div key={date}>
                <DateHeader date={date} />
                {rows.map((t) => (
                  <TxnRow key={t.id} txn={t} onClick={() => setEditing(t)} format={format} accounts={accounts} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="txn-list">
            {sorted.map((t) => (
              <TxnRow
                key={t.id}
                txn={t}
                onClick={() => setEditing(t)}
                format={format}
                showDate
                accounts={accounts}
              />
            ))}
          </div>
        )}
      </div>

      {editing && (
        <EditTxnModal
          txn={editing}
          categories={categories}
          accounts={accounts}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            reload()
          }}
        />
      )}
      {creating && (
        <CreateTxnModal
          categories={categories}
          accounts={accounts}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false)
            reload()
          }}
        />
      )}
    </>
  )
}

function DateHeader({ date }: { date: string }) {
  const d = new Date(`${date}T00:00:00`)
  const today = new Date()
  const isToday = d.toDateString() === today.toDateString()
  const yest = new Date(today); yest.setDate(today.getDate() - 1)
  const isYesterday = d.toDateString() === yest.toDateString()
  const label = isToday
    ? 'Today'
    : isYesterday
    ? 'Yesterday'
    : d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })

  return (
    <div
      style={{
        padding: '14px 8px 6px',
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        color: 'var(--text-muted)',
      }}
    >
      {label}
    </div>
  )
}

function TxnRow({
  txn, onClick, format, showDate, accounts,
}: {
  txn: Transaction
  onClick: () => void
  format: (n: number) => string
  showDate?: boolean
  accounts?: Account[]
}) {
  const { mask, display, formatAs } = useCurrency()
  const style = categoryStyle(txn.category)
  const color = categoryColorHex(txn.category)
  const amtBase = Number(txn.amount_in_base)
  const amtNative = Number(txn.amount)
  const tone: 'pos' | 'neg' | 'muted' = amtBase > 0 ? 'pos' : amtBase < 0 ? 'neg' : 'muted'

  // When the transaction's native currency already matches the display currency,
  // skip the CLP roundtrip (which introduces FX drift) and format directly.
  const nativeMatchesDisplay = txn.currency !== 'CLP' && txn.currency === display
  const mainAmountStr = nativeMatchesDisplay
    ? `${amtNative > 0 ? '+' : ''}${formatAs(amtNative)}`
    : `${amtBase > 0 ? '+' : ''}${format(amtBase)}`
  const merchant = txn.normalized_description || txn.raw_description || '—'
  const account = accounts?.find((a) => a.id === txn.account_id)

  return (
    <div
      className="txn-row clickable"
      onClick={onClick}
      style={txn.archived ? { opacity: 0.55 } : undefined}
    >
      <div className="txn-icon" style={{ background: alpha(color, 0.15), color }} aria-hidden>
        {style.icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="txn-merchant">{merchant}</div>
        <div className="txn-meta">
          <span className="category-pill" style={{ color }}>
            <span className="dot" />
            {style.label}
          </span>
          {account && (
            <>
              <span className="sep">·</span>
              <span>{account.name}</span>
            </>
          )}
          {showDate && (
            <>
              <span className="sep">·</span>
              <span>{txn.date}</span>
            </>
          )}
          {txn.archived && (
            <>
              <span className="sep">·</span>
              <span style={{ color: 'var(--pending-text)' }}>Archived</span>
            </>
          )}
          {txn.txn_type && txn.txn_type !== 'other' && (
            <>
              <span className="sep">·</span>
              <span style={{ textTransform: 'capitalize' }}>{txn.txn_type.replace('_', ' ')}</span>
            </>
          )}
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div className={`txn-amount num ${tone}`}>
          {mainAmountStr}
        </div>
        {txn.currency !== 'CLP' && txn.currency !== display && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
            {mask(amtNative.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))} {txn.currency}
          </div>
        )}
      </div>
      <div style={{ width: 8 }} />
    </div>
  )
}

function EditTxnModal({
  txn, categories, accounts, onClose, onSaved,
}: {
  txn: Transaction
  categories: Category[]
  accounts: Account[]
  onClose: () => void
  onSaved: () => void
}) {
  const account = accounts.find((a) => a.id === txn.account_id)
  const [date, setDate] = useState(txn.date)
  const [amount, setAmount] = useState(txn.amount)
  const [category, setCategory] = useState(txn.category ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const tasks: Promise<unknown>[] = []
      if (date !== txn.date) tasks.push(api.transactions.setDate(txn.id, date))
      if (amount !== txn.amount) tasks.push(api.transactions.setAmount(txn.id, amount))
      if (category && category !== (txn.category ?? '')) {
        tasks.push(api.transactions.setCategory(txn.id, category, true))
      }
      await Promise.all(tasks)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  async function toggleArchive() {
    setSaving(true)
    try {
      if (txn.archived) await api.transactions.unarchive(txn.id)
      else await api.transactions.archive(txn.id)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  async function remove() {
    if (!confirm('Delete this transaction permanently? Use archive instead to keep dedup history.')) return
    setSaving(true)
    try {
      await api.transactions.remove(txn.id)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Edit transaction</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)' }}>
            {txn.normalized_description || '—'}
          </div>
          {txn.raw_description && txn.raw_description !== txn.normalized_description && (
            <div
              style={{
                fontSize: 12,
                color: 'var(--text-muted)',
                wordBreak: 'break-word',
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              }}
            >
              {txn.raw_description}
            </div>
          )}
        </div>
        {account && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>Source:</span>{' '}
            {account.name}{account.institution ? ` · ${account.institution}` : ''}
          </div>
        )}
        <label className="modal-field">
          Date
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="modal-field">
          Amount ({txn.currency})
          <input
            type="number"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <label className="modal-field">
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">—</option>
            {categories.map((c) => (
              <option key={c.id} value={c.name}>{c.name}</option>
            ))}
          </select>
        </label>
        {error && <div style={{ color: 'var(--negative-text)', fontSize: 12 }}>{error}</div>}
        <div className="modal-actions">
          <button className="btn danger" onClick={remove} disabled={saving}>Delete</button>
          <button className="btn" onClick={toggleArchive} disabled={saving}>
            {txn.archived ? 'Unarchive' : 'Archive'}
          </button>
          <div className="spacer" />
          <button className="btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CreateTxnModal({
  categories, accounts, onClose, onSaved,
}: {
  categories: Category[]
  accounts: Account[]
  onClose: () => void
  onSaved: () => void
}) {
  const [accountId, setAccountId] = useState<number | ''>(accounts[0]?.id ?? '')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState(accounts[0]?.native_currency ?? 'CLP')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [txnType, setTxnType] = useState<TxnType>('card_payment')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Selecting an account defaults the currency to that account's native one.
  const selectAccount = (id: number | '') => {
    setAccountId(id)
    if (typeof id === 'number') {
      const a = accounts.find((x) => x.id === id)
      if (a) setCurrency(a.native_currency)
    }
  }

  async function save() {
    if (!accountId || !amount.trim()) {
      setError('Account and amount are required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await api.transactions.create({
        account_id: Number(accountId),
        date,
        amount,
        currency,
        raw_description: description || undefined,
        txn_type: txnType,
        category: category || undefined,
      })
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Add transaction</h3>
        <label className="modal-field">
          Account
          <select
            value={accountId}
            onChange={(e) => selectAccount(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Select an account…</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.native_currency})
              </option>
            ))}
          </select>
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <label className="modal-field">
            Date
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="modal-field">
            Type
            <select value={txnType} onChange={(e) => setTxnType(e.target.value as TxnType)}>
              <option value="card_payment">Card payment</option>
              <option value="transfer">Transfer</option>
              <option value="deposit">Deposit</option>
              <option value="refund">Refund</option>
              <option value="direct_debit">Direct debit</option>
              <option value="fee">Fee</option>
              <option value="other">Other</option>
            </select>
          </label>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
          <label className="modal-field">
            Amount (negative for spend)
            <input
              type="number"
              step="0.01"
              placeholder="-12.34"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <label className="modal-field">
            Currency
            <input
              type="text"
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              maxLength={3}
            />
          </label>
        </div>
        <label className="modal-field">
          Description
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Grocery store"
          />
        </label>
        <label className="modal-field">
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Auto-categorize</option>
            {categories.map((c) => (
              <option key={c.id} value={c.name}>{c.name}</option>
            ))}
          </select>
        </label>
        {error && <div style={{ color: 'var(--negative-text)', fontSize: 12 }}>{error}</div>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Add transaction'}
          </button>
        </div>
      </div>
    </div>
  )
}

function SkeletonRows() {
  return (
    <div className="txn-list">
      {Array.from({ length: 8 }).map((_, i) => (
        <div className="txn-row" key={i}>
          <div className="skel" style={{ width: 36, height: 36, borderRadius: '50%' }} />
          <div style={{ flex: 1 }}>
            <div className="skel" style={{ height: 12, width: '40%', marginBottom: 6 }} />
            <div className="skel" style={{ height: 10, width: '24%' }} />
          </div>
          <div className="skel" style={{ height: 12, width: 80 }} />
        </div>
      ))}
    </div>
  )
}

function groupByDate(txns: Transaction[]): [string, Transaction[]][] {
  const map = new Map<string, Transaction[]>()
  for (const t of txns) {
    const list = map.get(t.date) ?? []
    list.push(t)
    map.set(t.date, list)
  }
  return Array.from(map.entries()).sort((a, b) => b[0].localeCompare(a[0]))
}

function alpha(hex: string, a: number): string {
  if (!hex.startsWith('#') || (hex.length !== 7 && hex.length !== 4)) {
    return `color-mix(in srgb, ${hex} ${a * 100}%, transparent)`
  }
  const full = hex.length === 4
    ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`
    : hex
  const r = parseInt(full.slice(1, 3), 16)
  const g = parseInt(full.slice(3, 5), 16)
  const b = parseInt(full.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}
