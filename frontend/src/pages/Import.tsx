import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type ImportPreview } from '../api/client'
import { useAccounts } from '../api/hooks'

const PARSERS = [
  { value: 'revolut', label: 'Revolut (CSV)' },
  { value: 'santander_es', label: 'Santander España (xlsx)' },
  { value: 'scotiabank_cl', label: 'Scotiabank Chile (xls)' },
]

const PREVIEW_LIMIT = 200

export function Import() {
  const qc = useQueryClient()
  const accounts = useAccounts().data ?? []
  const [accountId, setAccountId] = useState<number | ''>('')
  const [parser, setParser] = useState('revolut')
  const [statementYear, setStatementYear] = useState<number>(new Date().getFullYear())
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [committing, setCommitting] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  const yearArg = parser === 'scotiabank_cl' ? statementYear : undefined

  const refreshDashboards = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['transactions'] }),
      qc.invalidateQueries({ queryKey: ['spending'] }),
      qc.invalidateQueries({ queryKey: ['networth'] }),
    ])

  const doSyncEmail = async () => {
    setSyncing(true)
    setSyncError(null)
    setSyncResult(null)
    try {
      const r = await api.import.syncEmail()
      setSyncResult(
        `Fetched ${r.fetched} email(s), parsed ${r.parsed}, imported ${r.imported} new, skipped ${r.skipped} already-seen.`,
      )
      await refreshDashboards()
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : String(err))
    } finally {
      setSyncing(false)
    }
  }

  const doPreview = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    if (!file || !accountId) return
    try {
      setPreview(await api.import.preview(parser, accountId, file, yearArg))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const doCommit = async (force = false) => {
    if (!file || !accountId) return
    setCommitting(true)
    setError(null)
    try {
      const r = await api.import.commit(parser, accountId, file, force, yearArg)
      setResult(`Imported ${r.imported}, skipped ${r.duplicates_skipped} duplicate(s).`)
      setPreview(null)
      setFile(null)
      // New rows change spending, transactions, and net worth — refresh all three.
      await refreshDashboards()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCommitting(false)
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Sync from email</h2>
            <div className="card-meta">
              Pull Santander España transaction-notification emails for a near-live
              feed. These land as provisional rows; your monthly statement upload
              supersedes them. Re-running is safe — only new movements are added.
            </div>
          </div>
          <button className="btn primary" onClick={doSyncEmail} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync email'}
          </button>
        </div>
        {syncError && <div className="form-error" style={{ marginTop: 12 }}>{syncError}</div>}
        {syncResult && (
          <div style={{ marginTop: 12, color: 'var(--positive-text)', fontSize: 13, fontWeight: 500 }}>
            {syncResult}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Import statement</h2>
            <div className="card-meta">
              Pick the account and its bank format, then preview before committing.
              Duplicates are detected and skipped unless you force them.
            </div>
          </div>
        </div>

        {accounts.length === 0 ? (
          <div className="empty">
            No accounts yet. Add one in the <strong>Portfolio</strong> tab first, then
            come back to import its statements.
          </div>
        ) : (
          <form className="filters" onSubmit={doPreview}>
            <label>
              Account
              <select
                value={accountId}
                onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : '')}
                required
              >
                <option value="">— pick —</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.native_currency})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Parser
              <select value={parser} onChange={(e) => setParser(e.target.value)}>
                {PARSERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            {parser === 'scotiabank_cl' && (
              <label>
                Statement year
                <input
                  type="number"
                  value={statementYear}
                  onChange={(e) => setStatementYear(Number(e.target.value))}
                />
              </label>
            )}
            <label>
              File
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                required
              />
            </label>
            <button className="btn primary" type="submit" disabled={!file || !accountId}>
              Preview
            </button>
          </form>
        )}

        {error && <div className="form-error" style={{ marginTop: 12 }}>{error}</div>}
        {result && (
          <div style={{ marginTop: 12, color: 'var(--positive-text)', fontSize: 13, fontWeight: 500 }}>
            {result}
          </div>
        )}
      </div>

      {preview && (
        <div className="card">
          <div className="card-header">
            <div>
              <h2 className="card-title">Preview</h2>
              <div className="card-meta">
                <strong>{preview.total}</strong> rows parsed ·{' '}
                <strong>{preview.duplicates}</strong> already in the database
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn primary" onClick={() => doCommit(false)} disabled={committing}>
                {committing ? 'Importing…' : 'Import non-duplicates'}
              </button>
              <button
                className="btn"
                onClick={() => doCommit(true)}
                disabled={committing || preview.duplicates === 0}
              >
                Force import all
              </button>
            </div>
          </div>

          <PreviewTable preview={preview} />
        </div>
      )}
    </>
  )
}

function PreviewTable({ preview }: { preview: ImportPreview }) {
  const rows = preview.rows.slice(0, PREVIEW_LIMIT)
  return (
    <>
      <div style={{ overflowX: 'auto' }}>
        <table className="preview-table">
          <thead>
            <tr>
              <th>Date</th>
              <th className="num-col">Amount</th>
              <th>Cur</th>
              <th>Type</th>
              <th>Description</th>
              <th>Dup?</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={r.is_duplicate ? 'is-dup' : undefined}>
                <td>{r.date}</td>
                <td className="num num-col">{r.amount}</td>
                <td className="muted">{r.currency}</td>
                <td className="muted">{r.txn_type.replace('_', ' ')}</td>
                <td>{r.raw_description}</td>
                <td>{r.is_duplicate ? <span className="tag tag-warn">dup</span> : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview.rows.length > PREVIEW_LIMIT && (
        <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          Showing first {PREVIEW_LIMIT} of {preview.rows.length} rows. All rows are still
          imported on commit.
        </div>
      )}
    </>
  )
}
