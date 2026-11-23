import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from reviewer.history_api import make_handler, read_history


class HistoryTests(unittest.TestCase):
    def test_run_and_rerun_accept_local_vite_origins_and_reject_external_origins(self):
        manager = Mock()
        manager.start.return_value = {'id': 'ui-new', 'status': 'Running'}
        handler = make_handler(None, manager)
        handler.history = lambda self: ([{'id': 'ui-old', 'action': 'file:check'}], {})
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            for origin in ['http://localhost:5173', 'http://127.0.0.1:5174',
                           'http://localhost:4173', 'http://[::1]:5173']:
                for body in [{'command': 'file:check'}, {'rerunId': 'ui-old'}]:
                    with self.subTest(origin=origin, body=body):
                        req = Request(base + '/api/run', data=json.dumps(body).encode(),
                                      headers={'Content-Type': 'application/json', 'Origin': origin})
                        with urlopen(req) as response:
                            self.assertEqual(response.status, 202)
                            self.assertEqual(json.load(response)['id'], 'ui-new')
            self.assertEqual(manager.start.call_count, 8)
            for origin in ['https://example.com', 'http://localhost.evil.test:5173',
                           'null', 'http://192.168.1.10:5173', 'http://localhost:bad']:
                with self.subTest(origin=origin):
                    req = Request(base + '/api/run', data=b'{"command":"report"}',
                                  headers={'Content-Type': 'application/json', 'Origin': origin})
                    with self.assertRaises(HTTPError) as error:
                        urlopen(req)
                    self.assertEqual(error.exception.code, 403)
                    self.assertIn('local UI', json.load(error.exception)['message'])
                    error.exception.close()
            self.assertEqual(manager.start.call_count, 8)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_disconnected_client_does_not_receive_second_response(self):
        handler_type = make_handler(None)
        for failure in (ConnectionAbortedError(10053, 'aborted'),
                        ConnectionResetError('reset'), BrokenPipeError('closed')):
            with self.subTest(error=type(failure).__name__):
                handler = object.__new__(handler_type)
                handler.path = '/api/history'
                handler.send_response = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                handler.send_error = Mock()
                handler.wfile = Mock()
                handler.wfile.write.side_effect = failure
                with patch('reviewer.history_api.read_history', return_value=([], {})):
                    handler.do_GET()
                handler.send_response.assert_called_once_with(200)
                handler.send_error.assert_not_called()
                self.assertTrue(handler.close_connection)

    def test_file_read_failure_still_returns_503(self):
        handler = object.__new__(make_handler(None))
        handler.path = '/api/history'
        handler.send_error = Mock()
        with patch('reviewer.history_api.read_history', side_effect=PermissionError('locked')):
            handler.do_GET()
        handler.send_error.assert_called_once_with(503, 'Could not read automation files; retry shortly')

    def test_exports_in_a_configured_output_folder_are_linked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            logs, reports, custom = root / 'logs', root / 'reports', root / 'custom'
            for path in (logs, reports, custom):
                path.mkdir()
            pdf = custom / 'native.pdf'
            pdf.write_bytes(b'%PDF-test')
            extra = custom / 'SUPPLEMENTARY_filtered_messages_native.csv'
            extra.write_text('list')
            settings = SimpleNamespace(logs=logs, reports=reports, downloads=reports)
            with patch('reviewer.history_api.WORKSPACE', root), patch('reviewer.history_api.workflow_folders', return_value=(root, custom)):
                _, files = read_history(settings)
            self.assertEqual(set(files), {str(pdf.resolve()), str(extra.resolve())})
            with patch('reviewer.history_api.WORKSPACE', root), patch('reviewer.history_api.workflow_folders', side_effect=ValueError('broken')):
                self.assertEqual(read_history(settings)[1], {})

    def test_real_status_output_and_restricted_file_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            logs, outputs = root / 'logs', root / 'outputs'
            logs.mkdir()
            outputs.mkdir()
            pdf = outputs / 'report.pdf'
            pdf.write_bytes(b'%PDF-test')
            secret = root / 'secret.txt'
            secret.write_text('private')
            for name, extra in [('success', {'event': 'pdfVerified', 'data': {'output': str(pdf)}}),
                                ('failed', {'event': 'failure', 'data': {'message': 'Blocked'}}),
                                ('unknown', {'event': 'fileVerified', 'data': {}})]:
                events = [{'event': 'start', 'time': '2026-10-14T10:00:00Z', 'data': {'command': 'report'}}, extra]
                (logs / f'run-{name}.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n{', encoding='utf-8')
            settings = SimpleNamespace(logs=logs, reports=outputs, downloads=outputs)
            # Isolate from real files in the workspace's Output_report_files.
            for target, value in (('WORKSPACE', root), ('workflow_folders', Mock(return_value=(root, outputs)))):
                active = patch(f'reviewer.history_api.{target}', value)
                active.start()
                self.addCleanup(active.stop)
            records, _ = read_history(settings)
            self.assertEqual({r['status'] for r in records}, {'Success', 'Failed', 'Unknown'})
            success = next(r for r in records if r['status'] == 'Success')
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(settings))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base + '/api/history') as response:
                    self.assertEqual(len(json.load(response)['records']), 3)
                with urlopen(base + success['outputUrl']) as response:
                    self.assertEqual(response.read(), b'%PDF-test')
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/api/file?path=' + str(secret))
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
