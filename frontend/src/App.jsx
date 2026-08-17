import { useCallback, useEffect, useState } from 'react'
import './App.css'

// Why the reason values are hardcoded here to match the backend's REASON_*
// constants: the filter dropdown must send exactly the strings the API validates
// against, and a tiny fixed list is clearer (and needs no extra request) than
// fetching the enum. If a new reason is added, it is a one-line change in both
// places, which the tests would catch.
const REASONS = [
  { value: '', label: 'All reasons' },
  { value: 'missing_in_b', label: 'Missing in B' },
  { value: 'orphan_in_b', label: 'Orphan in B' },
  { value: 'duplicate_in_b', label: 'Duplicate in B' },
  { value: 'value_mismatch', label: 'Value mismatch' },
]

// Why a single top-level component: this is one screen with a handful of related
// controls, so splitting it into child components would add indirection without
// buying reuse. Local useState is the right amount of state management here - no
// Redux/Context needed for one page.
function App() {
  const [orgs, setOrgs] = useState([])
  const [orgId, setOrgId] = useState('')
  const [reason, setReason] = useState('')
  const [ordering, setOrdering] = useState('value')
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Load the org list once on mount (empty dependency array). Why auto-select the
  // first org: the disagreements API refuses to answer without an org_id, so
  // defaulting to one means the user sees data immediately instead of an error.
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

  // Why useCallback: this function is a dependency of the effect below, so
  // memoizing it (keyed on the filter inputs) prevents the effect from firing on
  // every render while still refetching whenever org/reason/ordering changes.
  const loadDisagreements = useCallback(() => {
    if (!orgId) return
    setLoading(true)
    setError('')
    // Why URLSearchParams: it encodes query values correctly (no manual string
    // concatenation bugs) and reason is only appended when set, so "All reasons"
    // sends no filter at all rather than an empty one.
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

  // Re-run the fetch whenever the memoized loader identity changes (i.e. when a
  // filter changes). This keeps the table in sync with the controls automatically.
  useEffect(() => {
    loadDisagreements()
  }, [loadDisagreements])

  // Why toggle between "value" and "-value": the brief asks to "sort by value",
  // and a single clickable header that flips ascending/descending is the smallest
  // UI that satisfies it. The server does the actual ordering so the client stays
  // dumb and consistent with API-side sorting.
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
          {/* Why a composite key with idx as a tiebreaker: a record_id can appear
              under more than one reason and orphans have no record_id at all, so
              no single field is unique; combining fields plus the index keeps
              React keys stable and warning-free. */}
          {rows.map((row, idx) => (
            <tr key={`${row.reason}-${row.record_id}-${row.b_entry_ids?.join(',')}-${idx}`}>
              <td>{row.reason}</td>
              <td>{row.record_id || '-'}</td>
              <td>{row.location_id}</td>
              <td>{row.a_value ?? row.b_value ?? '-'}</td>
              <td>{row.a_value_raw ?? '-'}</td>
              <td>{row.b_value_raw ?? '-'}</td>
              <td>{(row.b_entry_ids || []).join(', ') || '-'}</td>
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
