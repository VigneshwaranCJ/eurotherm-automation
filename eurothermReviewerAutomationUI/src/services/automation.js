async function request(path, options) {
  const response = await fetch(path, options)
  const text = await response.text()
  let data
  try {
    data = JSON.parse(text)
  } catch {
    if (response.status === 403 && text.includes('Origin does not match host')) {
      throw new Error('The backend is running an older version. Stop it with Ctrl+C, restart with python -m reviewer.history_api, then try again.')
    }
    throw new Error(`The server returned ${response.status} ${response.statusText || ''} instead of JSON. Check that the Python API is running and restart it after updates.`)
  }
  if (!response.ok) throw new Error(data.message || 'Could not complete request')
  return data
}

export async function fetchHistory(signal) {
  const data = await request('/api/history', { signal })
  if (!Array.isArray(data.records)) throw new Error('Invalid history response')
  return data
}

export function startRun(body) {
  return request('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function stopRun() {
  return request('/api/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
}

export function openFolder(kind) {
  return request('/api/open-folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind }) })
}


