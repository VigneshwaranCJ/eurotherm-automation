export default function Overview({ records, loading }) {
  const metrics = [
    ['Total records', records.length, 'All recorded activity', 'neutral'],
    ['Successful runs', records.filter((r) => r.status === 'Success').length, 'Completed with evidence', 'green'],
    ['Failed runs', records.filter((r) => r.status === 'Failed').length, 'Review details to investigate', 'red'],
    ['Running now', records.filter((r) => r.status === 'Running').length, 'Live automation activity', 'blue'],
  ]
  return <section className="overview" aria-label="Activity overview">{metrics.map(([label, value, hint, tone]) => <article className={`metric metric-${tone}`} key={label}><p><span className="metric-dot" />{label}</p><strong>{loading ? '—' : value}</strong><span>{hint}</span></article>)}</section>
}
