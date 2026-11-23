import { useState } from 'react'
import { groupByDate, labels } from '../utils/history'
import RunDetails from './RunDetails'
import StatusBadge from './StatusBadge'

export default function HistoryTable({ records, commands, workflow, busy, error, loading, updated, onRun, refresh }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('All')
  const filtered = records.filter((record) => (status === 'All' || record.status === status) &&
    [labels[record.action], record.action, record.output, record.message, record.time].filter(Boolean).join(' ').toLowerCase().includes(query.toLowerCase()))
  return (
    <section className="history-card" aria-label="Download history">
      <div className="card-heading"><div><h2>Activity history <span className="record-count">{records.length}</span></h2><p>Outputs, execution details, and logs in one place.</p></div><div className="history-sync"><span className="last-updated" role="status">{loading ? 'Loading history…' : error ? 'Updates paused' : updated ? `Updated ${updated} IST` : 'Waiting for updates'}</span><button className="secondary-button" onClick={refresh} disabled={loading}>Refresh</button></div></div>
      <div className="history-toolbar"><label className="search-field"><span aria-hidden="true">⌕</span><span className="sr-only">Search activity</span><input type="search" placeholder="Search actions, files, or errors…" value={query} onChange={(event) => setQuery(event.target.value)} /></label><label className="status-filter"><span>Status</span><select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}>{['All', 'Running', 'Success', 'Failed', 'Stopped', 'SKIPPED_NO_MESSAGES', 'Available', 'Unknown'].map((value) => <option key={value} value={value}>{value === 'All' ? 'All statuses' : value}</option>)}</select></label></div>
      <div className="table-scroll">
        <table>
          <caption>Success: completed with evidence. SKIPPED_NO_MESSAGES: Reviewer confirmed no messages, so no PDF was made. Available: existing output file. Unknown: no confirmed completion.</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Action</th><th scope="col">Status</th><th scope="col">Output file</th><th scope="col">Logs & details</th><th scope="col" className="align-right">Run</th></tr></thead>
          {groupByDate(filtered).map(([date, rows]) => (
            <tbody key={date}>
              {rows.map((record, index) => (
                <tr key={record.id} data-date={date}>
                  {index === 0 && <th className="date-cell" scope="rowgroup" rowSpan={rows.length}>{date}</th>}
                  <td className="action-cell" data-label="Action"><strong>{labels[record.action] || record.action}</strong><span className="record-time">{record.time && !Number.isNaN(new Date(record.time).getTime()) ? new Date(record.time).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' }) : 'Time unavailable'}</span>{record.message && <span className={`record-message ${record.status === 'Failed' ? 'failure-message' : ''}`} title={record.message}>{record.message}</span>}</td>
                  <td data-label="Status"><StatusBadge status={record.status} /></td>
                  <td data-label="Output file">{record.outputUrl ? <a className="file-link" href={record.outputUrl} target="_blank" rel="noreferrer">Open file ↗</a> : <span className="unavailable">No output</span>}{record.output && <details className="path-details"><summary title={record.output}>{record.output.split(/[\\/]/).pop()}</summary><span className="file-path">{record.output}</span></details>}</td>
                  <td data-label="Logs & details">{record.logUrl && <a href={record.logUrl} target="_blank" rel="noreferrer">View logs ↗</a>}<RunDetails record={record} /></td>
                  <td className="align-right" data-label="Run">{commands.includes(record.action) ? <button className="secondary-button" disabled={busy || !!error || (record.action.startsWith('workflow:') && !workflow?.ready)} title={busy ? 'Wait for the current automation to finish' : 'Start a new run with the current configuration'} onClick={() => onRun({ rerunId: record.id })}>Rerun</button> : <span className="unavailable">—</span>}</td>
                </tr>
              ))}
            </tbody>
          ))}
          {filtered.length === 0 && <tbody><tr><td colSpan="6" className="empty-state"><strong>{loading ? 'Loading your activity…' : error && !records.length ? 'Waiting for your backend' : records.length ? 'No matching activity' : 'Your activity starts here'}</strong><p>{records.length ? 'Try another search or status filter.' : 'Start a workflow above to see its progress and results.'}</p>{(query || status !== 'All') && <button className="secondary-button" onClick={() => { setQuery(''); setStatus('All') }}>Clear filters</button>}</td></tr></tbody>}
        </table>
      </div>
      <div className="table-footer"><span>{filtered.length} of {records.length} records</span><span>Dates grouped by day · IST</span></div>
    </section>
  )
}
