import hashlib
import tempfile
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from reviewer.config import WORKSPACE, Settings
from reviewer.pipeline.calendar import daily_intervals, date_folder, discover, organize, scan
from reviewer.pipeline.state import ProcessingState
from reviewer.pipeline.profiles import profile_settings
from reviewer.pipeline.configuration import PipelineConfig
from reviewer.pipeline.recovery import owner_active


class BatchTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    def test_local_recording_days_split_at_ist_midnight(self):
        metadata = dict(FirstSample='2026-10-13T17:00:00Z', LastSample='2026-10-13T20:00:00Z')
        days = daily_intervals(metadata, self.now)
        self.assertEqual([d['date'] for d in days], ['2026-10-13', '2026-10-14'])
        self.assertEqual(days[0]['end'], '2026-10-13T18:30:00.000Z')
        self.assertEqual(days[1]['start'], days[0]['end'])
        self.assertEqual(date_folder(self.root, date(2026, 10, 13)), self.root / '2026/Oct/13')

    def test_current_future_and_unreliable_dates_are_not_processed(self):
        for first, last in [('2026-10-15T18:30:00Z', '2026-10-16T02:00:00Z'),
                            ('2026-10-20T00:00:00Z', '2026-10-21T00:00:00Z')]:
            self.assertEqual(daily_intervals(dict(FirstSample=first, LastSample=last), self.now), [])
        with self.assertRaises(ValueError):
            daily_intervals(dict(FirstSample='bad', LastSample='bad'), self.now)

    def test_recursive_discovery_accepts_named_and_numeric_months(self):
        for name in ['2026/Oct/13/a.uhh', '2026/10/13/b.UHH', 'root.uhh', 'ignore.txt']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'input')
        self.assertEqual(len(discover(self.root)), 3)

    def test_organization_preserves_original_and_rejects_collisions(self):
        source = self.root / 'original.uhh'
        source.write_bytes(b'original')
        sha = hashlib.sha256(b'original').hexdigest()
        with patch('reviewer.pipeline.calendar.validate_file', return_value={'sha256': sha}):
            target = organize(source, self.root, date(2026, 10, 13), sha)
        self.assertTrue(source.is_file())
        self.assertEqual(target.read_bytes(), source.read_bytes())
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'collision'):
            organize(source, self.root, date(2026, 10, 13), hashlib.sha256(b'changed').hexdigest())
        self.assertEqual(target.read_bytes(), b'original')

    def test_scan_deduplicates_content_and_reports_unreadable_dates(self):
        for name in ['a.uhh', 'b.uhh']:
            (self.root / name).write_bytes(b'same')
        settings = Settings.load({})
        metadata = dict(FirstSample='2026-10-13T00:00:00Z', LastSample='2026-10-13T01:00:00Z')
        with patch('reviewer.pipeline.calendar.validate_file', return_value={'sha256': 'same-sha'}), patch('reviewer.pipeline.calendar.read_interval', return_value=metadata):
            rows = scan(settings, self.root, now=self.now)
        self.assertEqual([r['status'] for r in rows], ['Pending', 'Skipped'])
        with patch('reviewer.pipeline.calendar.validate_file', side_effect=RuntimeError('being written')):
            rows = scan(settings, self.root, organize_inputs=True, now=self.now)
        self.assertTrue(all(r['status'] == 'Failed' for r in rows))
        self.assertFalse((self.root / '2026').exists())

    def evidence(self):
        outputs = []
        for name in ['Channels_Logs.pdf', 'Pen_Logs.pdf', 'Message_Logs.pdf']:
            path = self.root / name
            path.write_bytes(b'%PDF-verified-fixture')
            outputs.append(dict(output=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        return outputs

    def test_sqlite_claims_completion_and_modified_output_recovery(self):
        state = ProcessingState(self.root / 'processing.sqlite')
        key = state.key({'source': 'sha', 'date': '2026-10-13'})
        self.assertTrue(state.claim(key, 'a.uhh', '2026-10-13'))
        with self.assertRaisesRegex(RuntimeError, 'active task'):
            state.claim(key, 'a.uhh', '2026-10-13')
        with self.assertRaises(ValueError):
            state.finish(key, 'Completed', dict(outputs=[]))
        outputs = self.evidence()
        state.finish(key, 'Completed', dict(outputs=outputs))
        self.assertFalse(ProcessingState(state.path).claim(key, 'a.uhh', '2026-10-13'))
        Path(outputs[0]['output']).write_bytes(b'corrupt')
        self.assertTrue(state.claim(key, 'a.uhh', '2026-10-13'))

    def test_retry_limit_and_safe_stop_recovery(self):
        state = ProcessingState(self.root / 'processing.sqlite')
        state.claim('task', 'file.uhh', '2026-10-13')
        state.finish('task', 'Failed', {'message': 'native error'})
        self.assertFalse(state.claim('task', 'file.uhh', '2026-10-13'))
        self.assertTrue(state.claim('task', 'file.uhh', '2026-10-13', retries=1))
        state.finish('task', 'Stopped', {})
        self.assertTrue(state.claim('task', 'file.uhh', '2026-10-13'))

    def test_dated_profiles_have_standardized_names_and_source_isolation(self):
        config = PipelineConfig(self.root, self.root / 'output', '', 'SLS709', 'groupName', (), (), True)
        settings = replace(Settings.load({}), recording_date='2026-10-13', source_key='File_02_abc')
        for profile, name in [('graph', 'SLS709_Channels_Logs.pdf'), ('pen-log', 'SLS709_Pen_Logs.pdf'), ('message-log', 'SLS709_Message_Logs.pdf')]:
            configured = profile_settings(settings, profile, config, 'run')
            self.assertEqual(configured.reports, config.output_dir / '2026/Oct/13/Reports/File_02_abc')
            self.assertEqual(configured.report_name, name)
        import os
        self.assertTrue(owner_active(os.getpid()))

    def test_batch_integrates_daily_logs_sqlite_and_native_adapter(self):
        from reviewer.pipeline.batch import run_batch
        source = self.root / 'source.uhh'
        source.write_bytes(b'source')
        sha = hashlib.sha256(b'source').hexdigest()
        config = PipelineConfig(self.root, self.root / 'output', '', 'SLS709', 'groupName', (), (), True)
        settings = replace(Settings.load({}), temp=self.root / 'temp', logs=self.root / 'logs')
        record = dict(source=str(source), sha256=sha, status='Pending', tasks=[dict(date='2026-10-13', start='2026-10-12T18:30:00.000Z', end='2026-10-13T18:30:00.000Z')])
        def native(command, daily, authorization, pipeline_config, on_event):
            self.assertEqual(authorization, sha)
            results = []
            for profile in ('graph', 'pen-log', 'message-log'):
                selected = profile_settings(daily, profile, config, 'run')
                path = selected.reports / selected.report_name
                path.write_bytes(b'%PDF-native-adapter-fixture')
                on_event('profileStarted', dict(profile=profile))
                on_event('profileComplete', dict(profile=profile))
                results.append(dict(output=str(path)))
            return results
        with patch('reviewer.pipeline.batch.roots', return_value=(self.root, config.output_dir)), patch('reviewer.pipeline.batch.STATUS', self.root / 'status.json'), patch('reviewer.pipeline.batch.DATABASE', self.root / 'state.sqlite'), patch('reviewer.pipeline.batch.PipelineConfig.load', return_value=config), patch('reviewer.pipeline.batch.scan', return_value=[record]), patch('reviewer.application.run.run_command', side_effect=native) as execute:
            result = run_batch(settings, 'batch:run')
            self.assertEqual(result['completedFiles'], 1)
            self.assertTrue((config.output_dir / '2026/Oct/13/Logs/processing_manifest.json').is_file())
            self.assertTrue((config.output_dir / '2026/Oct/13/Logs/execution.log').is_file())
            record['status'] = 'Pending'
            result = run_batch(settings, 'batch:run')
            self.assertEqual(result['completedFiles'], 1)
            execute.assert_called_once()
