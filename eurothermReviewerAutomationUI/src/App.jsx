import './App.css'
import RunControls from './components/RunControls'
import HistoryTable from './components/HistoryTable'
import Overview from './components/Overview'
import WorkflowSetup from './components/WorkflowSetup'
import ActiveRun from './components/ActiveRun'
import BatchControls from './components/BatchControls'
import { useAutomation } from './hooks/useAutomation'

function App() {
  const automation = useAutomation()
  const connected = !automation.loading && !automation.error
  return (
    <>
      <nav className="topbar" aria-label="Application">
        <a className="brand" href="#main"><span className="brand-mark" aria-hidden="true">E</span><span>EUROTHERM <span className="brand-light">REVIEWER</span></span></a>
        <span className={`connection ${connected ? 'online' : ''}`}><i aria-hidden="true" />{automation.loading ? 'Connecting' : connected ? 'System connected' : 'Connection lost'}</span>
      </nav>
      <main className="history-page" id="main">
        <header className="page-header">
          <div><p className="eyebrow">AUTOMATION WORKSPACE</p><h1>Download history</h1><p className="description">Run your workflows. Follow every result.</p></div>
          <span className="timezone">All dates & times in IST</span>
        </header>
        <Overview records={automation.records} loading={automation.loading} />
        <BatchControls {...automation} />
        <WorkflowSetup workflow={automation.workflow} />
        <ActiveRun record={automation.records.find((record) => record.status === 'Running')} />
        <RunControls commands={automation.commands} workflow={automation.workflow} busy={automation.busy} disconnected={!!automation.error} onRun={automation.launch} />
        {automation.runError && <div className="connection-error" role="alert"><strong>Couldn’t start automation</strong><p>{automation.runError}</p></div>}
        {automation.error && <div className="connection-error" role="alert"><strong>Backend connection unavailable</strong><p>{automation.error}{automation.records.length > 0 && ' Showing the last loaded records.'}</p></div>}
        <HistoryTable {...automation} onRun={automation.launch} />
        <footer className="page-footer"><span>Eurotherm Reviewer · Automation workspace</span><span>History updates automatically every 2 seconds</span></footer>
      </main>
    </>
  )
}

export default App
