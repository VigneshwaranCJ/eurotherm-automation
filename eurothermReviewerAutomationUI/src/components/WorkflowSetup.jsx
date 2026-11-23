import { useState } from 'react'

function Folder({ label, path }) {
  const [message, setMessage] = useState('')
  async function copy() {
    try { await navigator.clipboard.writeText(path); setMessage('Copied') }
    catch { setMessage('Select the path to copy') }
  }
  return <div className="setup-folder"><span>{label}</span><div><code>{path}</code><button className="secondary-button" onClick={copy} aria-label={`Copy ${label.toLowerCase()} path`}>Copy</button></div><small role="status">{message}</small></div>
}

export default function WorkflowSetup({ workflow }) {
  if (!workflow) return null
  const hasInput = !!workflow.inputFiles?.length
  const steps = [
    ['01', 'Automated UHH import', hasInput ? `${workflow.inputFiles.length} UHH file${workflow.inputFiles.length === 1 ? '' : 's'} in your input folder` : 'Automation imports UHH files from the input folder.', hasInput],
    ['02', 'Custom person & channels', workflow.channelCount === 25 ? `${workflow.recordId} · 25 configured channels` : 'Confirm the record ID and all 25 channel mappings.', workflow.channelCount === 25],
    ['03', 'Check workflow readiness', workflow.ready ? 'Choose Validate 25-channel workflow before exporting.' : 'Workflow controls unlock when configuration is complete.', workflow.ready],
  ]
  return <section className="setup-card" aria-label="25-channel workflow setup"><div className="setup-heading"><div><p className="eyebrow">25-CHANNEL WORKFLOW</p><h2>{workflow.ready ? 'Configuration complete' : 'Get your workflow ready'}</h2></div><span className={`setup-pill ${workflow.ready ? 'is-ready' : ''}`}>{workflow.ready ? 'Ready to validate' : 'Setup required'}</span></div><ol className="setup-steps">{steps.map(([number, title, hint, done]) => <li key={number} className={done ? 'step-done' : ''}><span className="step-number">{done ? '✓' : number}</span><div><strong>{title}</strong><p>{hint}</p></div></li>)}</ol><div className="setup-folders"><Folder label="Input folder" path={workflow.inputDirectory} /><Folder label="Export folder" path={workflow.outputDirectory} /></div>{workflow.issues?.length > 0 && <details className="setup-issues"><summary>View setup requirements ({workflow.issues.length})</summary><ul>{workflow.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></details>}</section>
}


