"""Local API for automation execution and download history."""
import json
import mimetypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse, unquote

from .config import Settings, WORKSPACE
from .ui_runs import RunManager, UI_COMMANDS
from .common.events import iter_events
from .pipeline.inputs import workflow_folders


def file_url(path):
    return '/api/file?path=' + quote(str(path), safe='')


def allowed_origin(origin):
    # Vite may forward the backend Host while retaining the browser's Origin.
    # Its port can change if another development server is already running.
    if origin is None:
        return True  # Non-browser clients still require application/json.
    try:
        parsed = urlparse(origin)
        port = parsed.port
        return (parsed.scheme in {'http', 'https'}
                and parsed.hostname in {'localhost', '127.0.0.1', '::1'}
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and (port is None or port > 0))
    except ValueError:
        return False


def read_history(settings):
    records, files, linked = [], {}, set()
    folders = {settings.reports, settings.downloads, WORKSPACE / 'Output_report_files'}
    try:
        folders.add(workflow_folders()[1])  # Exports go to the configured workflow output folder.
    except (ValueError, OSError):
        pass  # A broken configuration is reported by the setup panel.
    for folder in folders:
        if folder.is_dir():
            for path in folder.rglob('*'):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()) and path.suffix != '.part':
                    files[str(path.resolve())] = path.resolve()
    if settings.logs.is_dir():
        for path in settings.logs.glob('run-*.jsonl'):
            if path.is_symlink():
                continue
            start, first, failure, pdf, completed, skipped = None, None, None, None, False, None
            for event in iter_events(path):
                first = first or event
                kind = event.get('event')
                if kind == 'start':
                    start = start or event
                elif kind == 'failure':
                    failure = event
                elif kind == 'pdfVerified':
                    pdf = event
                elif kind == 'messageLogSkipped':
                    skipped = event
                if kind in {'complete', 'diagnosticsComplete', 'dryRunComplete', 'importSkipped'}:
                    completed = True
            if first is None:
                continue
            files[str(path.resolve())] = path.resolve()
            start = start or first
            output = (pdf.get('data') or {}).get('output') if pdf else None
            output = str(Path(output).resolve()) if output else None
            if output in files:
                linked.add(output)
            status = 'Failed' if failure else 'Success' if pdf or completed else 'Unknown'
            message = (failure.get('data') or {}).get('message', '') if failure else ''
            action = (start.get('data') or {}).get('command', 'Automation run')
            if skipped and not failure:
                data = skipped.get('data') or {}
                message = f"{data.get('status')}: {data.get('date')} {data.get('instrument')}. {data.get('reason')}"
                if action == 'workflow:messages':
                    status = data.get('status')
            records.append(dict(id=path.name, time=start.get('time'), action=action,
                                status=status, output=output,
                                outputUrl=file_url(output) if output in files else None,
                                logUrl=file_url(path.resolve()), message=message))
    for output, path in list(files.items()):
        if output in linked or path.name.startswith('run-') and path.suffix == '.jsonl':
            continue
        records.append(dict(id=output, time=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                            action='Output file', status='Available', output=output,
                            outputUrl=file_url(path), logUrl=None, message='Existing output; no matching run evidence.'))
    records.sort(key=lambda item: item.get('time') or '', reverse=True)
    return records, files


def make_handler(settings, manager=None):
    class Handler(BaseHTTPRequestHandler):
        def send_error(self, code, message=None, explain=None):
            self.send_json(code, {'message': message or self.responses.get(code, ('Request failed',))[0]})

        def history(self):
            records, files = read_history(settings)
            if manager:
                jobs, consoles, run_logs = manager.records()
                records = [r for r in records if r['id'] not in run_logs]
                for job in jobs:
                    if job['output']:
                        output = str(Path(job['output']).resolve())
                        job['outputUrl'] = file_url(output) if output in files else None
                    for artifact in job.get('outputs', []):
                        resolved = str(Path(artifact['path']).resolve())
                        artifact['url'] = file_url(resolved) if resolved in files else None
                records = jobs + records
                records.sort(key=lambda item: item.get('time') or '', reverse=True)
                files.update(consoles)
            return records, files

        def send_json(self, status, data):
            payload = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            try:
                self.serve_post()
            except ConnectionError:
                self.close_connection = True

        def serve_post(self):
            route = urlparse(self.path).path
            if not manager or route not in {'/api/run', '/api/upload', '/api/stop', '/api/open-folder'}:
                self.send_error(404)
                return
            origin = self.headers.get('Origin')
            if not allowed_origin(origin):
                self.send_json(403, {'message': 'Run requests must come from the local UI (localhost or 127.0.0.1).'})
                return
            if route == '/api/upload':
                from .uploads import store_upload
                if self.headers.get('Content-Type') != 'application/octet-stream':
                    self.send_error(415, 'Upload must contain one binary .UHH file')
                    return
                try:
                    with manager.lock:
                        if manager.process is not None and manager.process.poll() is None:
                            raise RuntimeError('Wait for the running automation before uploading another input')
                        result = store_upload(self.rfile, int(self.headers.get('Content-Length', '0')),
                                              unquote(self.headers.get('X-Filename', '')))
                    self.send_json(201, result)
                except ValueError as error:
                    self.send_json(400, {'message': str(error)})
                except RuntimeError as error:
                    self.send_json(409, {'message': str(error)})
                except OSError as error:
                    self.send_json(503, {'message': str(error)})
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send_error(415)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(size))
                if route == '/api/stop':
                    self.send_json(202, manager.stop())
                    return
                if route == '/api/open-folder':
                    import os
                    from .pipeline.batch import roots
                    if body.get('kind') not in {'input', 'output'}:
                        raise ValueError('Choose the input or output folder')
                    path = roots()[0 if body['kind'] == 'input' else 1]
                    if not path.is_dir():
                        raise ValueError('Folder does not exist yet')
                    os.startfile(path)
                    self.send_json(200, {'message': 'Folder opened'})
                    return
                command = body.get('command')
                if body.get('rerunId'):
                    rows, _ = self.history()
                    previous = next((r for r in rows if r['id'] == body['rerunId']), None)
                    if previous is None:
                        raise ValueError('Run not found')
                    command = previous['action']
                    if command == 'input:import':
                        body['inputSha256'] = previous.get('inputSha256')
                result = manager.start(command, input_sha=body.get('inputSha256')) if command == 'input:import' else manager.start(command)
                self.send_json(202, result)
            except (ValueError, AttributeError) as error:
                self.send_json(400, {'message': str(error)})
            except RuntimeError as error:
                self.send_json(409, {'message': str(error)})
            except OSError as error:
                self.send_json(503, {'message': str(error)})

        def do_GET(self):
            try:
                self.serve_get()
            except (ConnectionError, BrokenPipeError):
                # Reloading/navigating away can close the socket during a response.
                # There is no client left to receive an error response.
                self.close_connection = True

        def serve_get(self):
            route = urlparse(self.path)
            if route.path not in {'/api/history', '/api/file'}:
                self.send_error(404)
                return
            try:
                records, files = self.history()
                if route.path == '/api/history':
                    from .pipeline.configuration import inspect_plan
                    from .pipeline.batch import batch_status
                    payload = json.dumps({'records': records, 'commands': UI_COMMANDS, 'workflow': inspect_plan(), 'batch': batch_status()}).encode('utf-8')
                    content_type = 'application/json; charset=utf-8'
                else:
                    requested = parse_qs(route.query).get('path', [''])[0]
                    path = files.get(requested)
                    if path is None or path.is_symlink():
                        self.send_error(404, 'File is not a known output or run log')
                        return
                    payload = path.read_bytes()
                    content_type = 'text/plain; charset=utf-8' if path.suffix == '.jsonl' else mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(payload)
            except ConnectionError:
                raise
            except OSError:
                self.send_error(503, 'Could not read automation files; retry shortly')
    return Handler


if __name__ == '__main__':
    settings = Settings.load()
    server = ThreadingHTTPServer(('127.0.0.1', 8765), make_handler(settings, RunManager(settings)))
    print('History API: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
