import { useEffect, useRef, useState } from 'react'
import { fetchHistory, startRun, stopRun } from '../services/automation'

export function useAutomation() {
  const [records, setRecords] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [updated, setUpdated] = useState('')
  const [commands, setCommands] = useState([])
  const [workflow, setWorkflow] = useState(null)
  const [batch, setBatch] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [runError, setRunError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const launchPending = useRef(false)
  const busy = submitting || records.some((record) => record.status === 'Running')

  async function launch(body) {
    if (launchPending.current) return
    launchPending.current = true
    setSubmitting(true)
    setRunError('')
    try {
      const result = await startRun(body)
      setRecords((previous) => [result, ...previous.filter((r) => r.id !== result.id)])
      setRefreshKey((value) => value + 1)
    } catch (failure) {
      setRunError(failure.message)
    } finally {
      launchPending.current = false
      setSubmitting(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    let pending = false
    async function refresh() {
      if (pending) return
      pending = true
      try {
        const data = await fetchHistory(controller.signal)
        if (controller.signal.aborted) return
        setRecords(data.records)
        setCommands(data.commands || [])
        setWorkflow(data.workflow || null)
        setBatch(data.batch || null)
        setError('')
        setUpdated(new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' }))
      } catch (failure) {
        if (failure.name !== 'AbortError') setError('Cannot reach the backend. Start python -m reviewer.history_api in your activated Python terminal, then select Refresh.')
      } finally {
        pending = false
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    refresh()
    const timer = setInterval(refresh, 2000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [refreshKey])

  function refresh() { setRefreshKey((value) => value + 1) }
  async function stop() {
    try { await stopRun(); refresh() }
    catch (failure) { setRunError(failure.message) }
  }
  return { records, error, loading, updated, commands, workflow, batch, busy, runError, launch, refresh, stop }
}

