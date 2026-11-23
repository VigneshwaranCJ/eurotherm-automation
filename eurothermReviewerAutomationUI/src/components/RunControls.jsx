import { useState } from 'react'
import { labels } from '../utils/history'

const descriptions = {
  'input:import': 'Import the selected UHH from the input folder into Reviewer and verify successful data loading.',
  'workflow:channels': 'Import → Custom person ID → select each of 25 channels → Charts and Cursor Statistics → Preview → Download.',
  'workflow:pen': 'Import → Custom person ID → select all 25 channels → all Include options → Preview → Download.',
  'workflow:messages': 'Import → Custom person ID → select all 25 channels → all Include options except Charts and Values → Preview → Download.',
  'workflow:preview': 'Validate the Custom record, all 25 channels, and each report preview.',
  'workflow:run': 'Export graph, pen-log, and message-log PDFs. Verified exports are reused on rerun.',
  report: 'Generate and verify a native PDF report using your configured dates and group.',
  'report:dry': 'Validate the chart and report preview before downloading a PDF.',
  diagnostics: 'Check data availability, group identity, and reporting readiness.',
  datasources: 'Inspect instrument connections and the latest file transfer information.',
  discover: 'Check Reviewer access and inspect the import interface.',
  'file:check': 'Check the configured input file and verify its content hash.',
}

export default function RunControls({ commands, workflow, busy, disconnected, onRun }) {
  const [command, setCommand] = useState('report')
  const needsSetup = command.startsWith('workflow:') && !workflow?.ready
  return (
    <section className="run-controls" aria-label="Run automation">
      <div className="run-intro"><span className="run-icon" aria-hidden="true">▷</span><div><h2>Start a workflow</h2><p>{busy ? 'Automation is in progress. Results will appear below.' : 'Choose an action to run on your connected Python backend.'}</p></div></div>
      <div className="scenario-options" aria-label="Report scenarios">{[
        ['workflow:channels', '01', 'Channels Logs', '25 channels individually', 'Charts + Cursor Statistics'],
        ['workflow:pen', '02', 'Pen Logs', 'All 25 channels', 'All Include options'],
        ['workflow:messages', '03', 'Message Logs', 'All 25 channels', 'All except Charts and Values'],
      ].map(([value, number, title, channels, options]) => <button key={value} type="button" aria-pressed={command === value} className={`scenario-option ${command === value ? 'selected' : ''}`} disabled={busy || !commands.includes(value)} onClick={() => setCommand(value)}><span>{number}</span><strong>{title}</strong><small>{channels}</small><small>{options}</small></button>)}</div>
      <div className="run-form"><div className="action-field"><label htmlFor="command">Automation action</label><select id="command" value={command} onChange={(event) => setCommand(event.target.value)} disabled={busy || commands.length === 0}>{commands.length === 0 && <option value="report">Waiting for backend…</option>}{commands.map((value) => <option key={value} value={value}>{labels[value] || value}</option>)}</select></div>
        <button className="primary-button" disabled={busy || disconnected || needsSetup || commands.length === 0} onClick={() => onRun({ command })}><span aria-hidden="true" className={busy ? 'spinner' : ''}>{busy ? '' : '▷'}</span>{busy ? 'Automation running…' : 'Run automation'}</button>
      </div>
      <div className="run-note"><span>{descriptions[command]}</span><small>Reruns use your current project configuration.</small></div>
      {needsSetup && workflow && <div className="workflow-setup"><strong>Workflow setup required</strong><p>Complete the input and channel mapping requirements in the setup checklist above. Your existing reporting actions are still available.</p></div>}
    </section>
  )
}
