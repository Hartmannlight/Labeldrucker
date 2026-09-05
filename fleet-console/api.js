export class FleetApiError extends Error {
  constructor(message, status, correlationId) {
    super(message)
    this.name = 'FleetApiError'
    this.status = status
    this.correlationId = correlationId
  }
}

export class FleetClient {
  constructor(token, fetchImpl = globalThis.fetch) {
    if (!token || !token.trim()) throw new Error('A PrinterFleet credential is required.')
    this.token = token.trim()
    this.fetchImpl = fetchImpl
  }

  async request(path, options = {}) {
    const correlationId = crypto.randomUUID()
    const response = await this.fetchImpl(`/api${path}`, {
      ...options,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${this.token}`,
        'X-Correlation-ID': correlationId,
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    })
    const responseCorrelationId = response.headers.get('X-Correlation-ID') || correlationId
    const contentType = response.headers.get('Content-Type') || ''
    const payload = contentType.includes('application/json') ? await response.json() : await response.text()
    if (!response.ok) {
      const detail = typeof payload === 'object' && payload && 'detail' in payload ? payload.detail : payload
      throw new FleetApiError(String(detail || `PrinterFleet request failed (${response.status}).`), response.status, responseCorrelationId)
    }
    return payload
  }

  printers() { return this.request('/v1/printers') }
  printerStatus(id) { return this.request(`/v1/printers/${encodeURIComponent(id)}/status`) }
  createPrinter(printer) {
    return this.request(`/v1/printers/${encodeURIComponent(printer.id)}`, {
      method: 'PUT', body: JSON.stringify(printer),
    })
  }
  updatePrinter(id, revision, settings) {
    return this.request(`/v1/printers/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify({ revision, settings }),
    })
  }
  pausePrinter(id, reason) {
    return this.request(`/v1/printers/${encodeURIComponent(id)}/pause`, {
      method: 'POST', body: JSON.stringify({ reason: reason || null }),
    })
  }
  resumePrinter(id) {
    return this.request(`/v1/printers/${encodeURIComponent(id)}/resume`, { method: 'POST' })
  }
  maintainPrinter(id, action) {
    return this.request(`/v1/printers/${encodeURIComponent(id)}/maintenance/${encodeURIComponent(action)}`, { method: 'POST' })
  }
  deliveries(query = '') { return this.request(`/v1/deliveries${query}`) }
  agents() { return this.request('/v1/agents') }
  discoverAgents(urls) {
    return this.request('/v1/agents/discover', { method: 'POST', body: JSON.stringify({ urls }) })
  }
  auditRecords() { return this.request('/v1/audit-records?limit=100') }
}

export function directPrinterDocument(values) {
  const protocol = values.protocol === 'serial_over_tcp' ? 'serial_over_tcp' : 'raw_tcp'
  const port = Number(values.port || (protocol === 'raw_tcp' ? 9100 : 0))
  if (!values.id.trim()) throw new Error('Printer ID is required.')
  if (!values.host.trim()) throw new Error('Printer host is required.')
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Port must be between 1 and 65535.')
  const width = Number(values.width)
  const height = Number(values.height)
  const dpi = Number(values.dpi)
  if (!(width > 0) || !(height > 0) || !(dpi > 0)) throw new Error('Media size and resolution must be positive.')
  return {
    id: values.id.trim(),
    name: values.name.trim() || values.id.trim(),
    site_id: values.site.trim() || 'default',
    driver: 'zpl',
    enabled: true,
    connection: { protocol, host: values.host.trim(), port, timeout_ms: 3000 },
    media: { loaded: { width_mm: width, height_mm: height, color: 'white' } },
    alignment: { dpi, offset_x_mm: 0, offset_y_mm: 0 },
    defaults: { copies: 1, rotation: 0 },
  }
}
