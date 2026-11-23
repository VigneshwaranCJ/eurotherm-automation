import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from reviewer.ui_runs import RunManager


class UiRunTests(unittest.TestCase):
    def test_overlap_completion_persistence_and_command_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(logs=Path(folder))
            manager = RunManager(settings)
            process = Mock()
            process.poll.return_value = None
            done = threading.Event()
            process.wait.side_effect = lambda: (done.wait(5), 1)[1]
            with patch('reviewer.ui_runs.subprocess.Popen', return_value=process) as launch:
                job = manager.start('report')
                self.assertEqual(job['status'], 'Running')
                self.assertEqual(launch.call_args.args[0][-2:], ['reviewer', 'report'])
                self.assertNotIn('shell', launch.call_args.kwargs)
                with self.assertRaises(RuntimeError):
                    manager.start('report')
                with self.assertRaises(ValueError):
                    manager.start('import:test')
                done.set()
                # Join the actual completion worker before checking persisted state.
                for worker in threading.enumerate():
                    if worker is not threading.current_thread() and worker.name.endswith('(finish)'):
                        worker.join(5)
                rows, files, _ = manager.records()
                self.assertEqual(rows[0]['status'], 'Failed')
                self.assertEqual(rows[0]['exitCode'], 1)
                self.assertEqual(len(files), 1)
                self.assertEqual(RunManager(settings).records()[0][0]['status'], 'Failed')

    def test_restart_does_not_claim_unconfirmed_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(logs=Path(folder))
            manager = RunManager(settings)
            manager.save(dict(id='ui-test', status='Running', message='started'))
            restarted = RunManager(settings)
            import json
            job = json.loads((restarted.folder / 'ui-test.json').read_text())
            self.assertEqual(job['status'], 'Unknown')

    def test_restart_recovers_failure_from_console_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(logs=Path(folder))
            manager = RunManager(settings)
            manager.save(dict(id='ui-test', status='Running', message='started'))
            (manager.folder / 'ui-test.log').write_text(
                '{"event":"failure","time":"2026-10-14T10:00:00Z","data":{"message":"Timed out"}}\n',
                encoding='utf-8')
            restarted = RunManager(settings)
            import json
            job = json.loads((restarted.folder / 'ui-test.json').read_text())
            self.assertEqual(job['status'], 'Failed')
            self.assertEqual(job['message'], 'Timed out')
