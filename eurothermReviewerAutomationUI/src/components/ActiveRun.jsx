import { labels, formatTimestamp, eventLabel } from '../utils/history'

export default function ActiveRun({ record }) {
  if (!record) return null
  const latest = record.details?.at(-1)
  return <section className="active-run" aria-label="Active automation"><div className="active-heading"><span className="spinner" aria-hidden="true" /><div><p className="eyebrow">RUN IN PROGRESS</p><h2>{labels[record.action] || record.action}</h2></div>{record.logUrl && <a href={record.logUrl} target="_blank" rel="noreferrer">Live logs ↗</a>}</div><div className="active-step"><span>Latest recorded event</span><strong>{latest ? eventLabel(latest.event) : 'Starting automation'}</strong><small>Started {formatTimestamp(record.time)}</small></div><p>Keep the backend running. Status and results update automatically.</p></section>
}
