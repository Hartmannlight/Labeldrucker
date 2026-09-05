import assert from 'node:assert/strict'
import test from 'node:test'
import { FleetApiError, FleetClient, directPrinterDocument } from '../api.js'

test('client sends an in-memory credential and correlation id through the same-origin proxy', async () => {
  let request
  const client = new FleetClient(' operator-secret ', async (url, options) => {
    request = { url, options }
    return new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Correlation-ID': 'server-id' } })
  })
  assert.deepEqual(await client.printers(), [])
  assert.equal(request.url, '/api/v1/printers')
  assert.equal(request.options.headers.Authorization, 'Bearer operator-secret')
  assert.match(request.options.headers['X-Correlation-ID'], /^[0-9a-f-]{36}$/)
})

test('client reports bounded API errors with the server correlation id', async () => {
  const client = new FleetClient('secret', async () => new Response(JSON.stringify({ detail: 'Printer is busy' }), {
    status: 409, headers: { 'Content-Type': 'application/json', 'X-Correlation-ID': 'request-42' },
  }))
  await assert.rejects(() => client.printerStatus('zebra / one'), error => {
    assert.ok(error instanceof FleetApiError)
    assert.equal(error.status, 409)
    assert.equal(error.correlationId, 'request-42')
    return true
  })
})

test('direct network printer documents normalize RAW defaults', () => {
  assert.deepEqual(directPrinterDocument({ id: ' zebra-1 ', name: '', site: '', protocol: 'raw_tcp', host: ' 192.0.2.10 ', port: '', width: '50', height: '25', dpi: '203' }), {
    id: 'zebra-1', name: 'zebra-1', site_id: 'default', driver: 'zpl', enabled: true,
    connection: { protocol: 'raw_tcp', host: '192.0.2.10', port: 9100, timeout_ms: 3000 },
    media: { loaded: { width_mm: 50, height_mm: 25, color: 'white' } },
    alignment: { dpi: 203, offset_x_mm: 0, offset_y_mm: 0 }, defaults: { copies: 1, rotation: 0 },
  })
})

test('serial bridges require an explicit valid port', () => {
  assert.throws(() => directPrinterDocument({ id: 'bridge', name: '', site: 'west', protocol: 'serial_over_tcp', host: 'bridge.local', port: '', width: '50', height: '25', dpi: '203' }), /Port must be/)
})
