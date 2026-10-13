"""Verify five PrintHub jobs produce ten rendered labels without resending jobs."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
from urllib.request import Request, urlopen
import uuid

API = os.getenv('CABLE_DEMO_API', 'http://127.0.0.1:8000')
EMULATOR = os.getenv('CABLE_DEMO_EMULATOR', 'http://virtual-zebra:9191')
TARGET = {'width_mm': float(os.getenv('CABLE_DEMO_WIDTH_MM', '75')),
          'height_mm': float(os.getenv('CABLE_DEMO_HEIGHT_MM', '50')), 'dpi': 203}
TEMPLATE = {
    'schema_version': 1, 'name': 'Synthetic paired-label burst',
    'layout': {'kind': 'leaf', 'padding_mm': [1, 1, 1, 1], 'elements': [{
        'type': 'text', 'text': 'FROM {from}\nTO {to}', 'fit': 'shrink_to_fit',
        'wrap': 'none', 'font_height_mm': 4, 'align_h': 'center', 'align_v': 'center',
    }]},
    'labels': [{'name': 'A'}, {'name': 'B', 'bindings': {'from': 'to', 'to': 'from'}}],
}


def request(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    with urlopen(Request(base + path, data=data, headers=headers), timeout=30) as response:
        return json.loads(response.read())


def main():
    before = {job['id'] for job in request(EMULATOR, '/api/jobs?limit=50')}
    run_id = uuid.uuid4().hex

    def submit(index):
        return request(API, '/v1/print-jobs', {
            'printer_id': 'virtual-zebra', 'template': TEMPLATE, 'target': TARGET,
            'variables': {'from': f'SW-DEMO-{index} [1]', 'to': 'SRV-DEMO [2]\nB0'},
            'output_mode': 'native', 'idempotency_key': f'burst-{run_id}-{index}',
            'origin': 'cable-demo-burst',
        })

    with ThreadPoolExecutor(max_workers=5) as workers:
        jobs = list(workers.map(submit, range(5)))
    print(f'Submitted {len(jobs)} jobs, expecting 10 labels', flush=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        outputs = [job for job in request(EMULATOR, '/api/jobs?limit=50') if job['id'] not in before]
        failures = [job for job in outputs if job['status'] == 'failed']
        if failures:
            raise RuntimeError(failures)
        if len(outputs) == 10 and all(job['status'] == 'rendered' and job['has_image'] for job in outputs):
            logical = [request(API, '/v1/print-jobs/' + job['id']) for job in jobs]
            if not all(job['status'] in ('transport_accepted', 'confirmed') and job['page_count'] == 2 for job in logical):
                raise RuntimeError(logical)
            print(json.dumps({'print_job_ids': [job['id'] for job in jobs], 'rendered_labels': len(outputs), 'failed_labels': 0}), flush=True)
            return
        time.sleep(.5)
    raise TimeoutError('Burst did not produce ten rendered labels within 90 seconds')


if __name__ == '__main__':
    main()
