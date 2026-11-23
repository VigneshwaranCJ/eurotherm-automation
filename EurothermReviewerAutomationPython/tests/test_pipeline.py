import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, MagicMock, patch

from reviewer.config import Settings, WORKSPACE
from reviewer.pipeline.configuration import PipelineConfig
from reviewer.pipeline.selection import select_record, validate_channels
from reviewer.pipeline.profiles import profile_settings
from reviewer.pipeline.journal import ExportJournal
from reviewer.instrument.validation import validate_file
from reviewer.pipeline.runner import execute_pipeline
from reviewer.reports.pdf import download_pdf
from contextlib import ExitStack


class PipelineTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.mappings = [dict(name=f'Channel {i}', selector=f'#channel-{i}') for i in range(1, 26)]
        self.channels = [dict(channelName=c['name'], dataPoints=[1, 2]) for c in self.mappings]
        self.config = PipelineConfig(self.root, self.root / 'exports', '', 'SLS709', 'groupName',
                                     tuple(self.mappings), ('Channel 1',), True)

    def test_missing_and_ambiguous_input_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'found 0'):
            self.config.select_input()
        (self.root / 'one.uhh').write_bytes(b'one')
        self.assertEqual(self.config.select_input().name, 'one.uhh')
        (self.root / 'two.UHH').write_bytes(b'two')
        with self.assertRaisesRegex(ValueError, 'found 2'):
            self.config.select_input()
        self.assertEqual(replace(self.config, filename='two.UHH').select_input().name, 'two.UHH')

    def test_missing_duplicate_and_empty_channels_fail(self):
        self.assertEqual(len(validate_channels(self.channels, self.mappings)), 25)
        for invalid in [self.channels[:-1], self.channels[:-1] + [self.channels[0]],
                        [dict(c, dataPoints=[]) for c in self.channels]]:
            with self.subTest(channels=invalid), self.assertRaises(ValueError):
                validate_channels(invalid, self.mappings)

    def test_record_selection_is_exact_and_unique(self):
        records = [dict(groupName='SLS709'), dict(groupName='SLS7090')]
        self.assertIs(select_record(records, 'SLS709', 'groupName'), records[0])
        for groups in [[], [records[0], records[0]]]:
            with self.assertRaises(ValueError):
                select_record(groups, 'SLS709', 'groupName')

    def test_profile_options_and_output_organization(self):
        settings = Settings.load({})
        pen = profile_settings(settings, 'pen-log', self.config, 'run-1')
        self.assertTrue(all([pen.include_chart, pen.include_values, pen.include_messages, pen.separate_messages, pen.cursor_statistics]))
        messages = profile_settings(settings, 'message-log', self.config, 'run-1')
        self.assertFalse(messages.include_chart or messages.include_values)
        self.assertTrue(messages.cursor_statistics and messages.separate_messages)
        graph = profile_settings(settings, 'graph', self.config, 'run-1')
        self.assertTrue(graph.include_chart and graph.cursor_statistics)
        self.assertFalse(graph.include_values or graph.include_messages or graph.separate_messages)
        self.assertTrue(messages.include_messages)
        self.assertEqual(messages.reports, self.root / 'exports/SLS709/run-1/message')
        self.assertEqual(pen.reports, self.root / 'exports/SLS709/run-1/pen')
        self.assertEqual(graph.reports, self.root / 'exports/SLS709/run-1/channel')

    def test_reports_with_the_same_identity_share_one_folder(self):
        identity = {'input': 'sha', 'channels': 25}
        first = ExportJournal(self.root / 'journal', identity)
        self.assertEqual(first.run_folder('run-1'), 'run-1')
        channel = self.root / 'run-1' / 'channel'
        channel.mkdir(parents=True)
        output = channel / 'report.pdf'
        output.write_bytes(b'%PDF-verified')
        first.commit('graph', dict(output=str(output)))
        later = ExportJournal(self.root / 'journal', identity)
        self.assertEqual(later.run_folder('run-2'), 'run-1')
        self.assertIsNotNone(later.cached('graph', channel))
        # A report left elsewhere by an older run is made again so the set stays together.
        self.assertIsNone(later.cached('graph', self.root / 'run-2' / 'channel'))
        self.assertEqual(ExportJournal(self.root / 'journal', {'input': 'other'}).run_folder('run-3'), 'run-3')

    def test_a_journal_from_before_shared_folders_starts_a_new_folder(self):
        folder = self.root / 'journal'
        old = ExportJournal(folder, {'input': 'sha'})
        scattered = self.root / 'old-run' / 'graph'
        scattered.mkdir(parents=True)
        output = scattered / 'report.pdf'
        output.write_bytes(b'%PDF-verified')
        old.commit('graph', dict(output=str(output)))
        current = ExportJournal(folder, {'input': 'sha'})
        run = current.run_folder('new-run')
        self.assertEqual(run, 'new-run')
        self.assertIsNone(current.cached('graph', self.root / run / 'channel'))
        self.assertEqual(output.read_bytes(), b'%PDF-verified')

    def test_checkpoints_require_verified_unchanged_files(self):
        output = self.root / 'report.pdf'
        output.write_bytes(b'%PDF-verified')
        journal = ExportJournal(self.root / 'journal', {'input': 'sha', 'channels': 25})
        self.assertIsNone(journal.cached('graph'))
        journal.commit('graph', dict(output=str(output)))
        self.assertIsNotNone(ExportJournal(self.root / 'journal', {'input': 'sha', 'channels': 25}).cached('graph'))
        self.assertIsNone(journal.cached('pen-log'))  # Interrupted before profile commit.
        output.write_bytes(b'corrupted')
        self.assertIsNone(journal.cached('graph'))
        self.assertIsNone(ExportJournal(self.root / 'journal', {'input': 'different'}).cached('graph'))
        output.unlink()
        self.assertIsNone(journal.cached('graph'))

    def test_configuration_rejects_unapproved_channels_and_paths(self):
        path = self.root / 'workflow.json'
        value = dict(record_id='SLS709', record_field='groupName', channels=self.mappings)
        path.write_text(json.dumps(value))
        self.assertEqual(len(PipelineConfig.load(path).channels), 25)
        for change in [dict(channels=self.mappings[:-1]), dict(record_field='person'),
                       dict(channels=[self.mappings[0]] * 25), dict(graph_channels=['Unknown']),
                       dict(input_file='../outside.uhh'), dict(cursor_statistics='true')]:
            path.write_text(json.dumps(dict(value, **change)))
            with self.subTest(change=change), self.assertRaises(ValueError):
                PipelineConfig.load(path)

    def test_invalid_file_types_and_empty_input(self):
        wrong = self.root / 'data.txt'
        wrong.write_text('not UHH')
        with self.assertRaisesRegex(ValueError, '.UHH'):
            validate_file(wrong)
        empty = self.root / 'empty.uhh'
        empty.touch()
        with self.assertRaisesRegex(RuntimeError, 'empty'):
            validate_file(empty)

    def runner_dependencies(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        names = ('read_interval', 'all_groups', 'import_evidence', 'import_single_file',
                 'select_group', 'check_duplicate', 'inspect_sources', 'identity',
                 'run_preflight', 'configured_interval', 'open_chart', 'select_channels',
                 'configure_print', 'validate_preview', 'download_pdf', 'fetch_messages', 'write_filtered_messages')
        mocks = {name: stack.enter_context(patch(f'reviewer.pipeline.runner.{name}')) for name in names}
        mocks['fetch_messages'].return_value = ([dict(content='message')], [])
        mocks['write_filtered_messages'].return_value = None
        record = dict(groupId='custom-1', groupName='SLS709', instrument=dict(instrumentName='Instrument', macAddress='MAC'))
        mocks['all_groups'].return_value = [record]
        mocks['select_group'].return_value = record
        mocks['import_evidence'].return_value = dict(status='already-imported')
        mocks['check_duplicate'].return_value = dict(status='already-imported')
        mocks['identity'].return_value = (dict(InstrumentName='Instrument'), dict(MacAddr='MAC'))
        mocks['run_preflight'].return_value = dict(start='2026-10-01T00:00:00Z', end='2026-10-02T00:00:00Z')
        mocks['open_chart'].side_effect = lambda *args: dict(channels=self.channels.copy())
        mocks['select_channels'].return_value = self.channels
        def download(page, group, chart, settings, log):
            output = settings.reports / 'native.pdf'
            output.write_bytes(b'%PDF-test-verified-by-mock')
            return dict(output=str(output))
        mocks['download_pdf'].side_effect = download
        return mocks

    def test_three_profiles_and_safe_rerun_reuse(self):
        mocks = self.runner_dependencies()
        settings = replace(Settings.load({}), logs=self.root / 'logs')
        args = ('workflow:run', settings, self.config, dict(sha='source-sha', token=None), Mock(), 'run-1', Mock())
        execute_pipeline(*args)
        self.assertEqual(mocks['download_pdf'].call_count, 3)
        self.assertEqual(mocks['validate_preview'].call_count, 3)
        execute_pipeline(*args)
        self.assertEqual(mocks['download_pdf'].call_count, 3)
        mocks['import_single_file'].assert_not_called()

    def test_preview_failure_prevents_export(self):
        mocks = self.runner_dependencies()
        mocks['validate_preview'].side_effect = RuntimeError('Invalid preview')
        with self.assertRaisesRegex(RuntimeError, 'Invalid preview'):
            execute_pipeline('workflow:run', replace(Settings.load({}), logs=self.root / 'logs'),
                             self.config, dict(sha='sha', token=None), Mock(), 'run-1', Mock())
        mocks['download_pdf'].assert_not_called()

    def test_preview_never_imports_missing_data(self):
        mocks = self.runner_dependencies()
        mocks['import_evidence'].return_value = dict(status='not-imported')
        with self.assertRaisesRegex(RuntimeError, 'verified existing import'):
            execute_pipeline('workflow:preview', Settings.load({}), self.config,
                             dict(sha='sha', token=None), Mock(), 'run-1', Mock())
        mocks['import_single_file'].assert_not_called()

    def test_each_scenario_exports_only_its_requested_profile(self):
        for command, profile in [('workflow:channels', 'channel'), ('workflow:pen', 'pen'), ('workflow:messages', 'message')]:
            with self.subTest(command=command):
                mocks = self.runner_dependencies()
                settings = replace(Settings.load({}), logs=self.root / command.replace(':', '-'))
                execute_pipeline(command, settings, self.config, dict(sha='sha', token=None), Mock(), 'run-scenario', Mock())
                mocks['download_pdf'].assert_called_once()
                self.assertEqual(mocks['download_pdf'].call_args.args[3].reports.name, profile)
                self.assertEqual(len(mocks['select_channels'].call_args.args[3]), 25)

    def test_failed_pdf_validation_does_not_publish_final_output(self):
        settings = replace(Settings.load({}), reports=self.root, logs=self.root)
        page = MagicMock()
        download = page.expect_download.return_value.__enter__.return_value.value
        download.failure.return_value = None
        download.save_as.side_effect = lambda path: Path(path).write_bytes(b'%PDF-test')
        document = Mock()
        document.pages = [Mock()]
        document.pages[0].extract_text.return_value = 'wrong report'
        with patch('pypdf.PdfReader', return_value=document), patch('reviewer.reports.pdf.verify_text', side_effect=RuntimeError('wrong identity')):
            with self.assertRaisesRegex(RuntimeError, 'wrong identity'):
                download_pdf(page, dict(groupName='SLS709'), dict(channels=[]), settings, Mock())
        self.assertEqual(list(self.root.glob('*.pdf')), [])
        self.assertEqual(len(list(self.root.glob('*.part'))), 1)

    def test_valid_pdf_is_published_after_validation(self):
        settings = replace(Settings.load({}), reports=self.root, logs=self.root)
        page = MagicMock()
        download = page.expect_download.return_value.__enter__.return_value.value
        download.failure.return_value = None
        download.suggested_filename = 'native.pdf'
        download.save_as.side_effect = lambda path: Path(path).write_bytes(b'%PDF-test')
        document = Mock()
        document.pages = [Mock()]
        document.pages[0].extract_text.return_value = 'verified report'
        with patch('pypdf.PdfReader', return_value=document), patch('reviewer.reports.pdf.verify_text', return_value={}), patch('reviewer.reports.pdf.verify_page_count', return_value=1):
            result = download_pdf(page, dict(groupName='SLS709'), dict(channels=[]), settings, Mock())
        self.assertTrue(Path(result['output']).is_file())
        self.assertEqual(list(self.root.glob('*.part')), [])
