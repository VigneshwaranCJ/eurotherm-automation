import { useId, useRef } from 'react'
import { labels, formatTimestamp, eventLabel } from '../utils/history'

export default function RunDetails({ record }) {
  const dialog = useRef(null)
  const titleId = useId()
  return <>
    <button className="details-button" onClick={() => dialog.current.showModal()}>Run details</button>
    <dialog ref={dialog} className="run-dialog" aria-labelledby={titleId} onClick={(event) => { if (event.target === dialog.current) dialog.current.close() }}>
      <div className="dialog-heading"><div><p className="eyebrow">EXECUTION DETAILS</p><h2 id={titleId}>{labels[record.action] || record.action}</h2></div><button className="close-dialog" aria-label="Close run details" onClick={() => dialog.current.close()}>×</button></div>
      <div className="dialog-content">
        <div className={`result-banner result-${record.status.toLowerCase()}`}><strong>{record.status}</strong><p>{record.message || 'No additional message recorded.'}</p></div>
        <dl className="run-facts"><div><dt>Started · IST</dt><dd>{formatTimestamp(record.time)}</dd></div><div><dt>Finished · IST</dt><dd>{record.finished ? formatTimestamp(record.finished) : record.status === 'Running' ? 'In progress' : 'Not recorded'}</dd></div></dl>
        {record.exitCode != null && <p className="exit-code">Exit code: {record.exitCode}</p>}
        {!!record.outputs?.length && <section className="export-list"><h3>Exported files</h3>{record.outputs.map((artifact) => <div key={artifact.path}>{artifact.url ? <a href={artifact.url} target="_blank" rel="noreferrer">{artifact.path.split(/[\\/]/).pop()} ↗</a> : <span>{artifact.path}</span>}{artifact.reused && <small>Reused verified export</small>}{artifact.supplementary && <small className="supplementary-note">Supplementary list, not a native Reviewer report</small>}</div>)}</section>}
        <section className="event-section"><h3>Execution timeline</h3>{record.details?.length ? <ol className="event-timeline">{record.details.map((event, i) => <li key={`${event.time}-${i}`}><div><strong>{eventLabel(event.event)}</strong><time>{event.time ? formatTimestamp(event.time) : 'Time not recorded'}</time></div><details><summary>Event data</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details></li>)}</ol> : <p className="muted">No structured events recorded. Open the full log for more information.</p>}</section>
      </div>
      <div className="dialog-footer">{record.logUrl && <a href={record.logUrl} target="_blank" rel="noreferrer">Open full log ↗</a>}<button className="secondary-button" onClick={() => dialog.current.close()}>Done</button></div>
    </dialog>
  </>
}
