export const labels = {
  report: 'Download chart / PDF',
  'batch:run': 'Start dated batch automation',
  'batch:scan': 'Scan recording dates',
  'batch:organize': 'Organize dated input folders',
  'input:import': 'Import UHH into Reviewer',
  'workflow:preview': 'Validate 25-channel workflow',
  'workflow:run': 'Export graph, pen & message logs',
  'workflow:channels': 'Channels Logs',
  'workflow:pen': 'Pen Logs',
  'workflow:messages': 'Message Logs',
  'report:dry': 'Validate report preview',
  full: 'Full workflow',
  'file:check': 'Check input file',
  diagnostics: 'Run diagnostics',
  datasources: 'Inspect data sources',
  discover: 'Discover Reviewer',
}

const dateFormat = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })

export function groupByDate(records) {
  const groups = new Map()
  records.forEach((record) => {
    const stamp = new Date(record.time)
    const date = Number.isNaN(stamp.getTime()) ? 'Unknown date' : dateFormat.format(stamp)
    if (!groups.has(date)) groups.set(date, [])
    groups.get(date).push(record)
  })
  return [...groups]
}

export function formatTimestamp(value) {
  const stamp = value ? new Date(value) : null
  if (!stamp || Number.isNaN(stamp.getTime())) return 'Not recorded'
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(stamp)
}

export function eventLabel(value = '') {
  const words = value.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]/g, ' ').toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : 'Automation event'
}
