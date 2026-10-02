import { Suspense, lazy, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { api, type Account, type AccountType, type FintualFund, type Holding } from '../api/client'
import {
  useNetworthCurrent, useNetworthHistory, useHoldings, useAccounts,
} from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { chart } from '../design/chartTheme'
import { MoneyTooltip } from '../components/MoneyTooltip'
import { PageLoading } from '../components/PageLoading'

// Health Review is its own chunk — it's the largest page and most visits stay
// on the overview sub-tab.
const PortfolioHealth = lazy(() =>
  import('./portfolio-health').then((m) => ({ default: m.PortfolioHealth })),
)

type PortfolioView = 'overview' | 'health'

// Wrapper: the net-worth/holdings overview and the Portfolio Health Review live
// behind one sidebar entry, switched by an in-page sub-tab (mirrors Forecast).
export function Portfolio() {
  const [view, setView] = useState<PortfolioView>('overview')
  return (
    <>
      <div className="subtabs">
        {(['overview', 'health'] as const).map((v) => (
          <button
            key={v}
            className={`subtab${view === v ? ' active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'overview' ? 'Overview' : 'Health Review'}
          </button>
        ))}
      </div>
      {view === 'overview' ? (
        <PortfolioOverview />
      ) : (
        <Suspense fallback={<PageLoading />}>
          <PortfolioHealth />
        </Suspense>
      )}
    </>
  )
}

function PortfolioOverview() {
  const { format, formatCompact, mask } = useCurrency()
  const qc = useQueryClient()
  const networthQ = useNetworthCurrent()
  const historyQ = useNetworthHistory()
  const holdingsQ = useHoldings()
  const accountsQ = useAccounts()

  const networth = networthQ.data ?? null
  const history = historyQ.data ?? []
  const holdings = holdingsQ.data ?? []
  const accounts = useMemo(() => accountsQ.data ?? [], [accountsQ.data])

  const [snapshotting, setSnapshotting] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [showAddAccount, setShowAddAccount] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)

  // Any write touches several of these; invalidating all is cheap and keeps the
  // page consistent (net worth depends on accounts + holdings + prices).
  const reload = () => qc.invalidateQueries()

  const onSnapshot = async () => {
    setSnapshotting(true)
    try {
      await api.networth.snapshot()
      await reload()
    } finally {
      setSnapshotting(false)
    }
  }

  const onDelete = async (id: number) => {
    await api.holdings.remove(id)
    await reload()
  }

  const onManualPrice = async (id: number, currentPrice: string | null) => {
    const next = prompt('Manual price (leave empty to clear)', currentPrice ?? '')
    if (next === null) return
    await api.holdings.setManualPrice(id, next.trim() === '' ? null : next.trim())
    await reload()
  }

  const accountById = useMemo(
    () => Object.fromEntries(accounts.map((a) => [a.id, a])),
    [accounts],
  )

  const investmentAccounts = accounts.filter((a) => a.type === 'investment')

  const loading = networthQ.isLoading || holdingsQ.isLoading || accountsQ.isLoading
  if (loading) return <PortfolioSkeleton />

  const total = Number(networth?.total_in_base ?? 0)
  const cash = Number(networth?.cash_total_in_base ?? 0)
  const inv = Number(networth?.holdings_total_in_base ?? 0)

  const historyPoints = history.map((p) => ({
    date: p.date,
    label: shortDate(p.date),
    value: Number(p.total_in_base),
  }))

  return (
    <>
      {/* Net worth tile + history */}
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Net worth</h2>
            <div className="card-meta">Cash + holdings, valued at today's FX and prices</div>
          </div>
          <button className="btn" onClick={onSnapshot} disabled={snapshotting}>
            {snapshotting ? 'Snapshotting…' : 'Snapshot today'}
          </button>
        </div>

        <div className="networth-tiles">
          <Tile label="Total" value={format(total)} emphasis />
          <Tile label="Cash" value={format(cash)} />
          <Tile label="Investments" value={format(inv)} />
        </div>

        {historyPoints.length === 0 ? (
          <div className="empty" style={{ marginTop: 16 }}>
            No snapshots yet. Click <strong>Snapshot today</strong> to record one — the
            chart fills in over time.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={historyPoints} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="g-networth" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1b5fd9" stopOpacity={0.32} />
                  <stop offset="100%" stopColor="#1b5fd9" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={chart.grid.stroke} vertical={false} />
              <XAxis dataKey="label" {...chart.axis} dy={6} />
              <YAxis
                {...chart.axis}
                tickFormatter={(v) => formatCompact(Number(v))}
                width={56}
              />
              <Tooltip
                cursor={chart.cursor}
                content={<MoneyTooltip format={format} />}
              />
              <Area
                type="monotone"
                dataKey="value"
                name="Net worth"
                stroke="#1b5fd9"
                strokeWidth={2}
                fill="url(#g-networth)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Cash balances */}
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Accounts</h2>
            <div className="card-meta">
              One row per real-world account — checking, savings, brokerage,
              debt. Balance is the cash sitting there in its native currency.
              For investment <em>positions</em> (SPY, UBER, …), add a Holding below.
            </div>
          </div>
          <button className="btn" onClick={() => setShowAddAccount((s) => !s)}>
            {showAddAccount ? 'Cancel' : '+ Add account'}
          </button>
        </div>
        {showAddAccount && (
          <AddAccountForm
            onCreated={async () => { setShowAddAccount(false); await reload() }}
          />
        )}
        {accounts.length === 0 ? (
          <div className="empty">No accounts yet.</div>
        ) : (
          <div className="balances-table">
            <div className="balances-head">
              <span>Account</span>
              <span>Type</span>
              <span className="num-col">Cash</span>
              <span className="num-col">Holdings</span>
              <span className="num-col">Total</span>
              <span />
            </div>
            {accounts.map((a) => {
              const acctRow = networth?.by_account.find((r) => r.account_id === a.id)
              const cashBase = acctRow ? Number(acctRow.cash_in_base) : 0
              const holdingsBase = acctRow ? Number(acctRow.holdings_in_base) : 0
              const totalBase = acctRow ? Number(acctRow.total_in_base) : cashBase + holdingsBase
              return (
                <div key={a.id} className="balances-row">
                  <span style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontWeight: 500 }}>{a.name}</span>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {a.balance_updated_at
                        ? `cash updated ${new Date(a.balance_updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
                        : 'cash not set'}
                    </span>
                  </span>
                  <span className="muted">{a.type}</span>
                  <span className="num num-col" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                    <span>{mask(fmtNative(a.current_balance, a.native_currency))}</span>
                    <span className="muted" style={{ fontSize: 11 }}>{format(cashBase)}</span>
                  </span>
                  <span className="num num-col">
                    {holdingsBase > 0 ? format(holdingsBase) : <span className="muted">—</span>}
                  </span>
                  <span className="num num-col" style={{ fontWeight: 600 }}>
                    {format(totalBase)}
                  </span>
                  <span className="holding-actions">
                    <button
                      className="link-btn"
                      onClick={async () => {
                        const next = prompt(
                          `New balance for ${a.name} (${a.native_currency})`,
                          a.current_balance,
                        )
                        if (next === null) return
                        await api.accounts.setBalance(a.id, next.trim())
                        await reload()
                      }}
                    >
                      edit
                    </button>
                    <button
                      className="link-btn danger"
                      onClick={async () => {
                        if (!confirm(`Delete account "${a.name}"? Its transactions and holdings will also be removed.`)) return
                        await api.accounts.remove(a.id)
                        await reload()
                      }}
                    >
                      delete
                    </button>
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Holdings */}
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Holdings</h2>
            <div className="card-meta">
              Individual investment positions (one row per ticker), grouped
              under an investment account.{' '}
              {holdings.length > 0 &&
                `${holdings.length} ${holdings.length === 1 ? 'position' : 'positions'}.`}
            </div>
          </div>
          <button className="btn" onClick={() => setShowAdd((s) => !s)}>
            {showAdd ? 'Cancel' : '+ Add holding'}
          </button>
        </div>

        {showAdd && (
          <HoldingForm
            accounts={investmentAccounts}
            onDone={async () => { setShowAdd(false); await reload() }}
          />
        )}

        {holdings.length > 0 && (
          <div className="holdings-table">
            <div className="holdings-head">
              <span>Ticker</span>
              <span>Account</span>
              <span className="num-col">Quantity</span>
              <span className="num-col">Price</span>
              <span className="num-col">Value</span>
              <span />
            </div>
            {holdings.map((h) => editingId === h.id ? (
              <div key={h.id} style={{ margin: '8px 0' }}>
                <HoldingForm
                  // A holding may sit under a non-investment account; keep it selectable.
                  accounts={investmentAccounts.some((a) => a.id === h.account_id)
                    ? investmentAccounts
                    : [...investmentAccounts, ...(accountById[h.account_id] ? [accountById[h.account_id]] : [])]}
                  holding={h}
                  onCancel={() => setEditingId(null)}
                  onDone={async () => { setEditingId(null); await reload() }}
                />
              </div>
            ) : (
              <div key={h.id} className="holdings-row">
                <span className="holding-ticker">
                  <span className="holding-symbol">{h.ticker}</span>
                  <span className="holding-class">{h.asset_class}</span>
                </span>
                <span className="muted">{accountById[h.account_id]?.name ?? '—'}</span>
                <span className="num num-col">{mask(fmtQty(h.quantity))}</span>
                <span className="num num-col" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                  <span>
                    {mask(fmtNative(h.price, h.price_currency))}
                  </span>
                  {h.is_manual && (
                    <span className={`tag ${h.missing_price ? 'tag-warn' : 'tag-info'}`}>
                      {h.missing_price ? 'no price' : `manual · ${shortDate(h.as_of)}`}
                    </span>
                  )}
                </span>
                <span className="num num-col">{format(Number(h.value_in_base))}</span>
                <span className="holding-actions">
                  <button
                    className="link-btn"
                    onClick={() => setEditingId(h.id)}
                    title="Edit holding"
                  >
                    edit
                  </button>
                  <button
                    className="link-btn"
                    onClick={() => onManualPrice(h.id, h.manual_price)}
                    title="Set or clear manual price"
                  >
                    price
                  </button>
                  <button
                    className="link-btn danger"
                    onClick={() => onDelete(h.id)}
                    title="Delete holding"
                  >
                    delete
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

function Tile({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className={`networth-tile${emphasis ? ' emphasis' : ''}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value num">{value}</div>
    </div>
  )
}

function AddAccountForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState<AccountType>('checking')
  const [country, setCountry] = useState('CL')
  const [currency, setCurrency] = useState('CLP')
  const [balance, setBalance] = useState('0')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name) return
    setSubmitting(true)
    setErr(null)
    try {
      await api.accounts.create({
        name,
        institution: null,
        country: country.toUpperCase(),
        type,
        native_currency: currency.toUpperCase(),
        current_balance: balance || '0',
      })
      onCreated()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to create account')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="add-holding" onSubmit={submit}>
      <input placeholder="Name (e.g. IBKR)" value={name} onChange={(e) => setName(e.target.value)} />
      <select value={type} onChange={(e) => setType(e.target.value as AccountType)}>
        <option value="checking">checking</option>
        <option value="savings">savings</option>
        <option value="credit">credit</option>
        <option value="investment">investment</option>
        <option value="debt">debt</option>
      </select>
      <input
        placeholder="Country (ES)"
        value={country}
        maxLength={2}
        onChange={(e) => setCountry(e.target.value.toUpperCase())}
      />
      <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
        <option value="CLP">CLP</option>
        <option value="EUR">EUR</option>
        <option value="USD">USD</option>
        <option value="GBP">GBP</option>
      </select>
      <input
        placeholder="Balance"
        value={balance}
        onChange={(e) => setBalance(e.target.value)}
        inputMode="decimal"
      />
      <span />
      <button className="btn primary" disabled={submitting}>
        {submitting ? 'Adding…' : 'Add'}
      </button>
      {err && <div className="form-error">{err}</div>}
    </form>
  )
}

// Create a holding, or edit one when `holding` is given.
function HoldingForm({
  accounts,
  holding,
  onDone,
  onCancel,
}: {
  accounts: Account[]
  holding?: Holding
  onDone: () => void
  onCancel?: () => void
}) {
  const [accountId, setAccountId] = useState<number | ''>(holding?.account_id ?? accounts[0]?.id ?? '')
  const [ticker, setTicker] = useState(holding?.ticker ?? '')
  const [quantity, setQuantity] = useState(holding ? String(Number(holding.quantity)) : '')
  const [priceCurrency, setPriceCurrency] = useState(holding?.price_currency ?? 'USD')
  const [assetClass, setAssetClass] = useState(holding?.asset_class ?? 'equity')
  const [manualPrice, setManualPrice] = useState(
    holding?.manual_price != null ? String(Number(holding.manual_price)) : '',
  )
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (accountId === '' || !ticker || !quantity) return
    setSubmitting(true)
    setErr(null)
    const payload = {
      account_id: Number(accountId),
      ticker,
      quantity: quantity.trim(),
      price_currency: priceCurrency,
      asset_class: assetClass,
      manual_price: manualPrice.trim() === '' ? null : manualPrice.trim(),
    }
    try {
      if (holding) await api.holdings.update(holding.id, payload)
      else await api.holdings.create(payload)
      onDone()
    } catch (e) {
      setErr(e instanceof Error ? e.message : holding ? 'Failed to save holding' : 'Failed to add holding')
    } finally {
      setSubmitting(false)
    }
  }

  if (accounts.length === 0) {
    return (
      <div className="empty" style={{ marginBottom: 12 }}>
        First create an account of type <strong>investment</strong> in the
        Accounts section above (e.g. "IBKR", "Fintual"). Then come back here to
        add positions like SPY or UBER to it.
      </div>
    )
  }

  const onPickFintual = (f: FintualFund) => {
    setTicker(f.ticker)
    setPriceCurrency(f.currency || 'CLP')
    // Fintual funds are fixed-income/multi-asset portfolios; "bond" is the
    // closest single-bucket fit in the current taxonomy.
    setAssetClass('bond')
  }

  return (
    <>
      {!holding && <FintualLookup onPick={onPickFintual} />}
      <form className="add-holding" onSubmit={submit}>
        <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <input
          placeholder="Ticker (SPY or FINTUAL:186)"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
        />
        <input
          placeholder="Quantity"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          inputMode="decimal"
        />
        <select value={priceCurrency} onChange={(e) => setPriceCurrency(e.target.value)}>
          <option value="USD">USD</option>
          <option value="EUR">EUR</option>
          <option value="CLP">CLP</option>
          <option value="GBP">GBP</option>
        </select>
        <select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
          <option value="equity">equity</option>
          <option value="bond">bond</option>
          <option value="cash">cash</option>
          <option value="crypto">crypto</option>
          <option value="other">other</option>
        </select>
        <input
          placeholder="Manual price (optional)"
          value={manualPrice}
          onChange={(e) => setManualPrice(e.target.value)}
          inputMode="decimal"
        />
        <span style={{ display: 'flex', gap: 6 }}>
          {onCancel && (
            <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
              Cancel
            </button>
          )}
          <button className="btn primary" disabled={submitting}>
            {holding ? (submitting ? 'Saving…' : 'Save') : (submitting ? 'Adding…' : 'Add')}
          </button>
        </span>
        {err && <div className="form-error">{err}</div>}
      </form>
    </>
  )
}

function FintualLookup({ onPick }: { onPick: (f: FintualFund) => void }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<FintualFund[]>([])
  const [searching, setSearching] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const term = q.trim()
    if (term.length < 2) return
    setSearching(true)
    setErr(null)
    try {
      const r = await api.prices.fintualSearch(term)
      setResults(r.results)
      if (r.results.length === 0) setErr('No Fintual funds match that name.')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="fintual-lookup">
      <form className="fintual-lookup-search" onSubmit={submit}>
        <input
          placeholder="Find a Fintual fund (e.g. Risky Norris)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn" type="submit" disabled={searching || q.trim().length < 2}>
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>
      {err && <div className="form-error" style={{ marginTop: 6 }}>{err}</div>}
      {results.length > 0 && (
        <div className="fintual-results">
          {results.map((r) => (
            <button
              key={r.ticker}
              type="button"
              className="fintual-result"
              onClick={() => {
                onPick(r)
                setResults([])
                setQ('')
              }}
            >
              <span style={{ fontWeight: 500 }}>{r.fund}</span>
              <span className="muted">serie {r.serie ?? '—'} · {r.ticker} · {r.currency}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function PortfolioSkeleton() {
  return (
    <>
      <div className="card">
        <div className="skel" style={{ height: 18, width: 140, marginBottom: 16 }} />
        <div className="skel" style={{ height: 80, marginBottom: 12 }} />
        <div className="skel" style={{ height: 200 }} />
      </div>
      <div className="card">
        <div className="skel" style={{ height: 18, width: 120, marginBottom: 16 }} />
        <div className="skel" style={{ height: 160 }} />
      </div>
    </>
  )
}

function fmtQty(q: string) {
  const n = Number(q)
  if (!Number.isFinite(n)) return q
  return n.toLocaleString('es-CL', { maximumFractionDigits: 4 })
}

function fmtNative(amount: string, currency: string) {
  const n = Number(amount)
  if (!Number.isFinite(n)) return amount
  // CLP has no minor unit in practice — render whole pesos. Other currencies
  // get standard 2dp (and up to 4 for tiny crypto-like fractions).
  const opts =
    currency === 'CLP'
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 4 }
  return `${n.toLocaleString('es-CL', opts)} ${currency}`
}

function shortDate(iso: string) {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
