import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { fetchHistory, startRun } from '../src/services/automation.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test('old backend HTML error explains how to restart', async () => {
  globalThis.fetch = async () => new Response('<!DOCTYPE HTML><p>Origin does not match host</p>', { status: 403 })
  await assert.rejects(startRun({ command: 'report' }), /restart with python -m reviewer.history_api/)
})

test('proxy HTML errors show HTTP status rather than a JSON parsing error', async () => {
  globalThis.fetch = async () => new Response('<html>Proxy unavailable</html>', { status: 502 })
  await assert.rejects(startRun({ command: 'report' }), /server returned 502/)
})

test('JSON API errors preserve the server explanation', async () => {
  globalThis.fetch = async () => Response.json({ message: 'Automation is already running.' }, { status: 409 })
  await assert.rejects(startRun({ command: 'report' }), /already running/)
})

test('successful run sends the command and returns its record', async () => {
  globalThis.fetch = async (path, options) => {
    assert.equal(path, '/api/run')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), { command: 'file:check' })
    return Response.json({ id: 'test-run', status: 'Running' }, { status: 202 })
  }
  assert.equal((await startRun({ command: 'file:check' })).status, 'Running')
})

test('history validates its response', async () => {
  globalThis.fetch = async () => Response.json({ records: null })
  await assert.rejects(fetchHistory(), /Invalid history response/)
})
