import { FleetApiError, FleetClient, directPrinterDocument } from './api.js'

const app = document.querySelector('#app')
let client = null
let view = 'printers'
let notice = null
let renderVersion = 0

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag)
  for (const [key, value] of Object.entries(attributes)) {
    if (key === 'className') node.className = value
    else if (key === 'text') node.textContent = value
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value)
    else if (value !== false && value != null) node.setAttribute(key, value === true ? '' : String(value))
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child != null) node.append(child)
  }
  return node
}

function errorMessage(error) {
  if (error instanceof FleetApiError) return `${error.message} · correlation ${error.correlationId}`
  return error instanceof Error ? error.message : String(error)
}

function setNotice(tone, text) {
  notice = { tone, text }
  render()
}

function loginView() {
  const token = element('input', { type: 'password', name: 'token', autocomplete: 'off', required: true, autofocus: true })
  const form = element('form', { className: 'login-card', onsubmit: async (event) => {
    event.preventDefault()
    try {
      const candidate = new FleetClient(token.value)
      await candidate.printers()
      client = candidate
      token.value = ''
      notice = null
      render()
    } catch (error) { setNotice('error', errorMessage(error)) }
  } }, [
    element('span', { className: 'eyebrow', text: 'Physical printer control plane' }),
    element('h1', { text: 'PrinterFleet Console' }),
    element('p', { text: 'Enter an operator credential. It stays only in this browser tab’s memory and is never written to storage.' }),
    element('label', {}, [element('span', { text: 'Fleet bearer credential' }), token]),
    element('button', { type: 'submit', text: 'Connect' }),
  ])
  return element('main', { className: 'login-shell' }, [form])
}

function shell(content) {
  const nav = ['printers', 'deliveries', 'agents', 'audit'].map((name) => element('button', {
    className: view === name ? 'active' : '', text: name[0].toUpperCase() + name.slice(1),
    onclick: () => { view = name; notice = null; render() },
  }))
  return element('div', { className: 'shell' }, [
    element('aside', {}, [
      element('div', { className: 'brand' }, [element('strong', { text: 'PrinterFleet' }), element('span', { text: 'Console' })]),
      element('nav', {}, nav),
      element('button', { className: 'quiet', text: 'Disconnect', onclick: () => { client = null; notice = null; render() } }),
    ]),
    element('section', { className: 'content' }, [
      notice ? element('div', { className: `notice ${notice.tone}`, text: notice.text }) : null,
      content,
    ]),
  ])
}

function definition(label, value) {
  return element('div', {}, [element('dt', { text: label }), element('dd', { text: value == null || value === '' ? '—' : String(value) })])
}

async function printerPage() {
  const root = element('main', {}, [
    element('header', { className: 'page-heading' }, [element('span', { className: 'eyebrow', text: 'Devices and sites' }), element('h1', { text: 'Physical printers' }), element('p', { text: 'Network printers connect directly. PrintAgent is reserved for site-local USB, Bluetooth and serial devices.' })]),
    addPrinterPanel(),
    element('div', { className: 'loading', text: 'Loading printers…' }),
  ])
  try {
    const printers = await client.printers()
    root.lastChild.replaceWith(element('div', { className: 'grid' }, printers.length ? printers.map(printerCard) : [element('div', { className: 'empty', text: 'No printers are visible to this credential.' })]))
  } catch (error) { root.lastChild.replaceWith(element('div', { className: 'empty error', text: errorMessage(error) })) }
  return root
}

function addPrinterPanel() {
  const fields = {
    id: ['Public ID', 'warehouse-zebra'], name: ['Name', 'Warehouse Zebra'], site: ['Site', 'default'],
    host: ['Host or IP', '192.0.2.20'], port: ['TCP port', '9100'], width: ['Label width (mm)', '50'],
    height: ['Label height (mm)', '50'], dpi: ['Resolution (dpi)', '203'],
  }
  const inputs = Object.fromEntries(Object.entries(fields).map(([key, [label, placeholder]]) => [key, element('input', { name: key, placeholder, required: !['name', 'site'].includes(key) })]))
  const protocol = element('select', { name: 'protocol' }, [element('option', { value: 'raw_tcp', text: 'RAW TCP / JetDirect' }), element('option', { value: 'serial_over_tcp', text: 'Serial over TCP bridge' })])
  return element('details', { className: 'panel' }, [
    element('summary', { text: 'Add direct network printer' }),
    element('form', { className: 'form-grid', onsubmit: async (event) => {
      event.preventDefault()
      try {
        const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value]))
        const printer = directPrinterDocument({ ...values, protocol: protocol.value })
        await client.createPrinter(printer)
        setNotice('success', `Printer ${printer.id} registered.`)
      } catch (error) { setNotice('error', errorMessage(error)) }
    } }, [
      ...Object.entries(inputs).slice(0, 4).map(([key, input]) => element('label', {}, [element('span', { text: fields[key][0] }), input])),
      element('label', {}, [element('span', { text: 'Connection' }), protocol]),
      ...Object.entries(inputs).slice(4).map(([key, input]) => element('label', {}, [element('span', { text: fields[key][0] }), input])),
      element('button', { type: 'submit', text: 'Register printer' }),
    ]),
  ])
}

function printerCard(printer) {
  const paused = Boolean(printer.control?.paused)
  const status = element('pre', { className: 'status', text: 'Status not queried.' })
  const actions = element('div', { className: 'actions' }, [
    element('button', { text: 'Read status', onclick: async () => {
      status.textContent = 'Querying device…'
      try { status.textContent = JSON.stringify(await client.printerStatus(printer.id), null, 2) } catch (error) { status.textContent = errorMessage(error) }
    } }),
    element('button', { text: paused ? 'Resume queue' : 'Pause queue', onclick: async () => {
      try {
        if (paused) await client.resumePrinter(printer.id)
        else await client.pausePrinter(printer.id, window.prompt('Why is this queue being paused?') || '')
        setNotice('success', `${printer.id} ${paused ? 'resumed' : 'paused'}.`)
      } catch (error) { setNotice('error', errorMessage(error)) }
    } }),
  ])
  for (const [action, label] of [['print-configuration', 'Print configuration'], ['print-network-configuration', 'Print network config'], ['calibrate-media', 'Calibrate media']]) {
    actions.append(element('button', { className: 'danger', text: label, onclick: async () => {
      if (!window.confirm(`${label} on ${printer.name || printer.id}? This operation may move label stock.`)) return
      try { await client.maintainPrinter(printer.id, action); setNotice('success', `${label} accepted by the device transport.`) } catch (error) { setNotice('error', errorMessage(error)) }
    } }))
  }
  const revision = Number(printer.registry?.revision)
  const nameInput = element('input', { value: printer.name || printer.id })
  actions.append(element('button', { text: 'Rename', disabled: !Number.isInteger(revision), onclick: async () => {
    try { await client.updatePrinter(printer.id, revision, { name: nameInput.value.trim() }); setNotice('success', `${printer.id} updated.`) } catch (error) { setNotice('error', errorMessage(error)) }
  } }))
  return element('article', { className: 'card' }, [
    element('div', { className: 'card-title' }, [element('div', {}, [element('h2', { text: printer.name || printer.id }), element('code', { text: printer.id })]), element('span', { className: paused ? 'badge warn' : 'badge', text: paused ? 'Paused' : 'Active' })]),
    element('dl', {}, [definition('Site', printer.site_id || 'default'), definition('Driver', printer.driver), definition('Media', printer.media?.loaded ? `${printer.media.loaded.width_mm} × ${printer.media.loaded.height_mm} mm` : null), definition('Resolution', printer.alignment?.dpi ? `${printer.alignment.dpi} dpi` : null)]),
    element('label', {}, [element('span', { text: 'Display name' }), nameInput]), actions, status,
  ])
}

async function deliveryPage() {
  const root = element('main', {}, [element('header', { className: 'page-heading' }, [element('span', { className: 'eyebrow', text: 'Durable delivery history' }), element('h1', { text: 'Queues and outcomes' })]), element('div', { className: 'loading', text: 'Loading deliveries…' })])
  try {
    const deliveries = await client.deliveries('?limit=100')
    const table = element('table', {}, [element('thead', {}, [element('tr', {}, ['Created', 'Printer', 'State', 'Attempts', 'Delivery'].map(text => element('th', { text })))])])
    const body = element('tbody')
    for (const item of deliveries) body.append(element('tr', {}, [element('td', { text: item.created_at || '—' }), element('td', { text: item.printer_id }), element('td', {}, [element('span', { className: `badge state-${item.state}`, text: item.state })]), element('td', { text: `${item.attempts ?? 0}/${item.max_attempts ?? '—'}` }), element('td', {}, [element('code', { text: item.id })])]))
    table.append(body); root.lastChild.replaceWith(element('div', { className: 'table-wrap' }, [table]))
  } catch (error) { root.lastChild.replaceWith(element('div', { className: 'empty error', text: errorMessage(error) })) }
  return root
}

async function agentsPage() {
  const urls = element('input', { placeholder: 'http://print-agent.example:8080' })
  const root = element('main', {}, [element('header', { className: 'page-heading' }, [element('span', { className: 'eyebrow', text: 'Edge connectivity' }), element('h1', { text: 'PrintAgents' }), element('p', { text: 'Agents are optional and used only when Fleet cannot reach a device transport directly.' })]), element('form', { className: 'inline-form', onsubmit: async (event) => { event.preventDefault(); try { await client.discoverAgents(urls.value.split(',').map(value => value.trim()).filter(Boolean)); setNotice('success', 'Agent discovery completed.') } catch (error) { setNotice('error', errorMessage(error)) } } }, [urls, element('button', { type: 'submit', text: 'Discover' })]), element('div', { className: 'loading', text: 'Loading agents…' })])
  try {
    const agents = await client.agents()
    root.lastChild.replaceWith(element('div', { className: 'grid' }, agents.length ? agents.map(agent => element('article', { className: 'card' }, [element('h2', { text: agent.agent_id || agent.id }), element('pre', { text: JSON.stringify(agent, null, 2) })])) : [element('div', { className: 'empty', text: 'No agents discovered.' })]))
  } catch (error) { root.lastChild.replaceWith(element('div', { className: 'empty error', text: errorMessage(error) })) }
  return root
}

async function auditPage() {
  const root = element('main', {}, [element('header', { className: 'page-heading' }, [element('span', { className: 'eyebrow', text: 'Global administration' }), element('h1', { text: 'Audit journal' })]), element('div', { className: 'loading', text: 'Loading audit records…' })])
  try {
    const records = await client.auditRecords()
    root.lastChild.replaceWith(element('div', { className: 'audit-list' }, records.map(record => element('article', { className: 'audit-row' }, [element('span', { text: record.created_at || '—' }), element('strong', { text: `${record.method} ${record.path}` }), element('span', { text: `${record.status_code} · ${record.actor}` }), element('code', { text: record.correlation_id })]))))
  } catch (error) { root.lastChild.replaceWith(element('div', { className: 'empty error', text: errorMessage(error) })) }
  return root
}

async function render() {
  const version = ++renderVersion
  const activeClient = client
  app.replaceChildren(client ? shell(element('div', { className: 'loading', text: 'Loading…' })) : loginView())
  if (!client) {
    if (notice) app.prepend(element('div', { className: `notice floating ${notice.tone}`, text: notice.text }))
    return
  }
  const pages = { printers: printerPage, deliveries: deliveryPage, agents: agentsPage, audit: auditPage }
  const content = await pages[view]()
  if (client === activeClient && version === renderVersion) app.replaceChildren(shell(content))
}

render()
