// "+ Update" slide-over: the monthly routine in one place. Every account's
// cash balance in a single form (with how old each one is), email sync, and a
// jump to statement import.
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type Account } from '../api/client'
import { queryKeys, useAccounts, useEmailSyncStatus } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { fmtNative } from '../lib/format'
import { useNav } from '../lib/nav'

// "8 min ago" / "3 h ago" / "2 d ago" for the last-sync line.
function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`
  return `${Math.round(mins / 1440)} d ago`
}

const STALE_DAYS = 30 // same threshold as the Needs-attention check

// Same skip rule as services/attention/checks.py: no balance to keep current.
const tracked = (a: Account) =>
  Number(a.current_balance) !== 0 || (a.balance_updated_at != null && a.type !== 'investment')

export function UpdatePanel({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const { go } = useNav()
  const { mask, privacy } = useCurrency()
  const accounts = (useAccounts().data ?? []).filter(tracked)
  const syncStatus = useEmailSyncStatus().data

  const [values, setValues] = useState<Record<number, string>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const changed = Object.entries(values).filter(([, v]) => v.trim() !== '')

  const saveBalances = async (e: React.FormEvent) => {
    e.preventDefault()
    if (changed.length === 0) return
    setSaving(true)
    setError(null)
    setSaved(null)
    try {
      await Promise.all(changed.map(([id, v]) => api.accounts.setBalance(Number(id), v.trim())))
      setValues({})
      setSaved(`Saved ${changed.length} ${changed.length === 1 ? 'balance' : 'balances'}.`)
      await Promise.all(
        [['networth'], queryKeys.accounts(), queryKeys.attention()].map((queryKey) =>
          qc.invalidateQueries({ queryKey }),
        ),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const syncEmail = async () => {
    setSyncing(true)
    setSyncMsg(null)
    try {
      const r = await api.import.syncEmail()
      qc.invalidateQueries({ queryKey: queryKeys.emailSyncStatus() })
      setSyncMsg(r.imported > 0
        ? `Imported ${r.imported} new ${r.imported === 1 ? 'transaction' : 'transactions'}.`
        : 'Up to date: no new transactions.')
      await Promise.all(
        [['transactions'], ['spending'], ['networth'], queryKeys.attention()].map((queryKey) =>
          qc.invalidateQueries({ queryKey }),
        ),
      )
    } catch (err) {
      setSyncMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <aside className="sheet" role="dialog" aria-label="Update" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-header">
          <h2 className="card-title">Update</h2>
          <button className="link-btn" onClick={onClose}>close</button>
        </div>

        <section className="sheet-section">
          <h3>Balances</h3>
          <p className="muted">Today&rsquo;s cash in each account. Leave a field empty to keep its balance.</p>
          {accounts.length === 0 ? (
            <div className="empty">No accounts with a balance yet. Add one under Portfolio.</div>
          ) : (
            <form onSubmit={saveBalances} className="sheet-balances">
              {accounts.map((a) => {
                const age = daysSince(a.balance_updated_at)
                const stale = age == null || age > STALE_DAYS
                return (
                  <label key={a.id} className="sheet-balance-row">
                    <span className="sheet-balance-name">
                      <span>{a.name}</span>
                      <span className={stale ? 'stale' : 'muted'}>
                        {age == null ? 'never set' : age === 0 ? 'updated today' : `updated ${age} ${age === 1 ? 'day' : 'days'} ago`}
                        {' · '}{mask(fmtNative(a.current_balance, a.native_currency))}
                      </span>
                    </span>
                    <span className="sheet-balance-input">
                      <input
                        inputMode="decimal"
                        value={values[a.id] ?? ''}
                        placeholder={privacy ? '••••' : String(Number(a.current_balance))}
                        onChange={(e) => setValues({ ...values, [a.id]: e.target.value })}
                      />
                      <span className="muted">{a.native_currency}</span>
                    </span>
                  </label>
                )
              })}
              {error && <div className="form-error">{error}</div>}
              <div className="sheet-actions">
                {saved && <span className="muted">{saved}</span>}
                <button className="btn primary" disabled={saving || changed.length === 0}>
                  {saving ? 'Saving…' : changed.length > 1 ? `Save ${changed.length} balances` : 'Save'}
                </button>
              </div>
            </form>
          )}
        </section>

        <section className="sheet-section">
          <h3>Transactions</h3>
          <div className="sheet-actions start">
            <button className="btn" onClick={syncEmail} disabled={syncing}>
              {syncing ? 'Syncing…' : 'Sync email'}
            </button>
            <button
              className="btn"
              onClick={() => {
                go('transactions', { view: 'import' })
                onClose()
              }}
            >
              Import a statement
            </button>
          </div>
          {syncMsg && <p className="muted">{syncMsg}</p>}
          {syncStatus && (
            <p className="muted">
              {syncStatus.last_ok === false
                ? `Last sync failed ${syncStatus.last_run_at ? ago(syncStatus.last_run_at) : ''}: ${syncStatus.last_error ?? 'unknown error'}`
                : syncStatus.last_run_at
                  ? `Last synced ${ago(syncStatus.last_run_at)}`
                  : 'Not synced yet'}
              {syncStatus.scheduled_times.length > 0
                ? ` · auto at ${syncStatus.scheduled_times.join(', ')}`
                : ' · auto-sync off'}
            </p>
          )}
        </section>
      </aside>
    </div>
  )
}

function daysSince(iso: string | null): number | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  return Math.max(0, Math.floor(ms / 86_400_000))
}
