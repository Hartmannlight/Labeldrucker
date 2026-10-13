"""Load the real Studio template and verify one print job containing two labels."""
from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

API = 'http://127.0.0.1:8000'
EMULATOR = 'http://virtual-zebra:9191'
OUTPUT = Path('/demo-output')
TEMPLATE_ID = 'kabel-demo-75x50'
REVISION = 'paced-label-set-v4'
TARGET = {'width_mm': 75, 'height_mm': 50, 'dpi': 203, 'origin_x_mm': 0, 'origin_y_mm': 0}


def request(method, path, body=None, *, token=None, base=API, binary=False):
    headers = {'Accept': 'image/png' if binary else 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    with urlopen(Request(base + path, data=data, headers=headers, method=method), timeout=45) as response:
        data = response.read()
        return data if binary else json.loads(data)


def print_and_verify(values, printer_id):
    before = {job['id'] for job in request('GET', '/api/jobs', base=EMULATOR)}
    job = request('POST', '/v1/print-jobs', {
        'template_id': TEMPLATE_ID, 'variables': values, 'target': TARGET,
        'printer_id': printer_id, 'output_mode': 'native',
        'idempotency_key': 'cable-demo-' + REVISION, 'origin': 'cable-demo',
    })
    print(f'Submitted one print job: {job["id"]}', flush=True)
    for _ in range(45):
        logical = request('GET', '/v1/print-jobs/' + job['id'])
        if logical['status'] in ('failed', 'held', 'cancelled', 'unconfirmed', 'outcome_unknown'):
            raise RuntimeError(logical.get('error') or logical.get('hold_reason') or logical['status'])
        received = sorted(
            (item for item in request('GET', '/api/jobs', base=EMULATOR) if item['id'] not in before),
            key=lambda item: item['created_at'],
        )
        for item in received:
            if item['status'] == 'failed':
                raise RuntimeError(f'Virtual printer failed: {item.get("error")}')
        if len(received) == 2 and all(item['status'] == 'rendered' and item['has_image'] for item in received):
            ends = {}
            for end, item in zip(('a', 'b'), received):
                png = request('GET', f'/api/jobs/{item["id"]}/image', base=EMULATOR, binary=True)
                if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Invalid virtual printer image')
                (OUTPUT / f'label-end-{end}.png').write_bytes(png)
                ends[end] = {'virtual_job_id': item['id']}
            if logical['page_count'] != 2:
                raise RuntimeError('PrintHub did not record both labels')
            print('Both labels received and rendered from the same print job.', flush=True)
            return {'print_job_id': job['id'], 'print_state': logical['status'], 'ends': ends}
        time.sleep(1)
    raise TimeoutError('Virtual printer did not produce both labels within 45 seconds')


def main():
    OUTPUT.mkdir(exist_ok=True)
    existing = OUTPUT / 'demo-result.json'
    if existing.exists():
        result = json.loads(existing.read_text())
        if result.get('revision') == REVISION:
            for end in ('a', 'b'):
                job = request('GET', '/api/jobs/' + result['ends'][end]['virtual_job_id'], base=EMULATOR)
                if job['status'] != 'rendered':
                    raise RuntimeError('Existing demo is no longer rendered')
            print('Prepared demo already exists; no duplicate jobs sent.', flush=True)
            return
    admin = Path('/run/printhub-secrets/printhub-admin-token').read_text().strip()
    catalog = request('GET', '/v1/printers')
    printer = next(item for item in catalog['printers'] if item.get('service_printer_id', item['id']) == 'virtual-zebra')
    connection = printer.get('service_connection_id', 'default')
    service_printer = printer.get('service_printer_id', 'virtual-zebra')
    request('PUT', f'/v1/printer-services/{connection}/printers/{service_printer}/media', {
        'display_name': 'Kabel-Faehnchen Demo 75 x 50 mm', 'width_mm': 75, 'height_mm': 50,
        'shape': 'rectangle', 'tracking': 'gap', 'print_technology': 'direct_thermal',
        'color': {'name': 'White', 'hex': '#ffffff'}, 'preferred_settings': {},
        'labels_available_at_load': 1000, 'low_warning_threshold': 10, 'custom': {},
    }, token=admin)
    source = Path('/demo/templates') / TEMPLATE_ID
    metadata = json.loads((source / 'metadata.json').read_text())
    payload = {key: value for key, value in metadata.items() if key != 'id'}
    payload['template'] = json.loads((source / 'template.json').read_text())
    payload['sample_data'] = json.loads((source / 'sample_data.json').read_text())
    template = request('PUT', '/v1/templates/' + TEMPLATE_ID, payload)
    if template.get('preview_warning'):
        raise RuntimeError('Template preview failed: ' + template['preview_warning'])
    values = template['print_defaults']
    check = request('POST', '/v1/renders/zpl', {'template': template['template'], 'variables': values, 'target': TARGET})
    if check.get('diagnostics') or check['zpl'].count('^XA') != 2:
        raise RuntimeError(f'Unexpected layout result: {check.get("diagnostics")}')
    printed = print_and_verify(values, printer['id'])
    result = {
        'revision': REVISION, 'template_id': TEMPLATE_ID, **printed,
        'urls': {
            'studio': f'http://localhost:8188/?template_id={TEMPLATE_ID}#/print',
            'printer': 'http://localhost:8191/', 'jobs': 'http://localhost:8188/#/jobs',
        },
    }
    existing.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
