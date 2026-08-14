import { useCallback, useEffect, useState } from 'react'
import './App.css'

const REASONS = [
  { value: '', label: 'All reasons' },
  { value: 'missing_in_b', label: 'Missing in B' },
  { value: 'orphan_in_b', label: 'Orphan in B' },
  { value: 'duplicate_in_b', label: 'Duplicate in B' },
  { value: 'value_mismatch', label: 'Value mismatch' },
]

function App() {
  const [orgs, setOrgs] = useState([])
  const [orgId, setOrgId] = useState('')
  const [reason, setReason] = useState('')
  const [ordering, setOrdering] = useState('value')
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch('/api/orgs/')
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load orgs (${r.status})`)
        return r.json()
      })
      .then((data) => {
        setOrgs(data)
        if (data.length && !orgId) {
          setOrgId(data[0].org_id)
        }
      })
      .catch((err) => setError(err.message))
  }, [])

  const loadDisagreements = useCallback(() => {
    if (!orgId) return
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ org_id: orgId, ordering })
    if (reason) params.set('reason', reason)
    fetch(`/api/disagreements/?${params}`)
      .then((r) => {
        if (!r.ok) {
          return r.json().then((body) => {
            throw new Error(body.detail || `Request failed (${r.status})`)
          })
        }
        return r.json()
      })
      .then((data) => {
        setRows(data.results || [])
        setCount(data.count || 0)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [orgId, reason, ordering])

  useEffect(() => {
    loadDisagreements()
  }, [loadDisagreements])

  function toggleValueSort() {
    setOrdering((prev) => (prev === 'value' ? '-value' : 'value'))
  }

  return (
    <div className="page">
      <h1>System disagreements</h1>
      <p className="lede">
        Records where System A and System B do not agree. Scoped to one org (tenant).
      </p>

      <div className="controls">
        <label>
          Org
          <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {orgs.map((o) => (
              <option key={o.org_id} value={o.org_id}>
                {o.org_id}
              </option>
            ))}
          </select>
        </label>

        <label>
          Reason
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => (
              <option key={r.value || 'all'} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>

        <button type="button" onClick={loadDisagreements}>
          Refresh
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p>Loading…</p>}

      <p className="meta">{count} disagreement{count === 1 ? '' : 's'}</p>

      <table>
        <thead>
          <tr>
            <th>Reason</th>
            <th>Record</th>
            <th>Location</th>
            <th>
              <button type="button" className="sort" onClick={toggleValueSort}>
                Value {ordering === 'value' ? '↑' : ordering === '-value' ? '↓' : ''}
              </button>
            </th>
            <th>A value</th>
            <th>B value</th>
            <th>B entries</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={`${row.reason}-${row.record_id}-${row.b_entry_ids?.join(',')}-${idx}`}>
              <td>{row.reason}</td>
              <td>{row.record_id || '—'}</td>
              <td>{row.location_id}</td>
              <td>{row.a_value ?? row.b_value ?? '—'}</td>
              <td>{row.a_value_raw ?? '—'}</td>
              <td>{row.b_value_raw ?? '—'}</td>
              <td>{(row.b_entry_ids || []).join(', ') || '—'}</td>
              <td>{row.detail}</td>
            </tr>
          ))}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={8}>No disagreements for this filter.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default App
