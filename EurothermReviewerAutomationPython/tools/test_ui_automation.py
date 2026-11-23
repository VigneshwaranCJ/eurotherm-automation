"""Exercise real UI API launches without imports or configuration changes."""
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reviewer.config import Settings
from reviewer.history_api import make_handler
from reviewer.ui_runs import RunManager


def main():
    # Browser validation runs headlessly for this test only.
    os.environ['HEADLESS'] = 'true'
    settings = Settings.load()
    folder = settings.logs / 'ui-runs'
    for path in folder.glob('*.json'):
        if json.loads(path.read_text())['status'] == 'Running':
            raise RuntimeError('An existing UI run is active; finish it before testing')
    manager = RunManager(settings)
    handler = make_handler(settings, manager)
    handler.log_message = lambda *args: None
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    results = []

    def request(path, body=None):
        req = Request(base + path, data=json.dumps(body).encode() if body else None,
                      headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=20) as response:
            return json.load(response)

    def run(body):
        job = request('/api/run', body)
        print(f"Started {job['action']}: {job['id']}", flush=True)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            record = next(r for r in request('/api/history')['records'] if r['id'] == job['id'])
            if record['status'] != 'Running':
                with urlopen(base + record['logUrl'], timeout=20) as response:
                    assert response.read(), 'Missing run console logs'
                results.append(record)
                print(json.dumps({k: record.get(k) for k in ('id', 'action', 'status', 'exitCode', 'message', 'output')}), flush=True)
                return record
            time.sleep(2)
        raise TimeoutError('Automation did not finish in 15 minutes')

    try:
        checked = run({'command': 'file:check'})
        assert checked['status'] == 'Success', checked['message']
        repeated = run({'rerunId': checked['id']})
        assert repeated['id'] != checked['id'] and repeated['status'] == 'Success'
        preview = run({'command': 'report:dry'})
        if preview['status'] == 'Success':
            report = run({'command': 'report'})
            if report.get('outputUrl'):
                with urlopen(base + report['outputUrl'], timeout=20) as response:
                    assert response.read(5) == b'%PDF-'
        output = settings.logs / 'ui-automation-smoke.json'
        output.write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(f'Results saved to {output}', flush=True)
    finally:
        output = settings.logs / 'ui-automation-smoke.json'
        output.write_text(json.dumps(results, indent=2), encoding='utf-8')
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
