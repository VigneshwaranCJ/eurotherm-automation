"""Import transport tests using fake files and mocked browser requests only."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, patch

from reviewer.config import ROOT, Settings
from reviewer.uhh import import_single_file


class ImportTransportTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.folder.cleanup)
        folder = Path(self.folder.name)
        self.file = folder / "fixture.uhh"
        self.file.write_bytes(b"fake test payload, never sent to Reviewer")
        self.sha = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.settings = replace(Settings.load({}), file=self.file, temp=folder, logs=folder, dry_run=False)
        self.page = MagicMock()
        self.control = self.page.locator.return_value
        self.control.evaluate.return_value = [self.file.name]
        self.response = self.page.expect_response.return_value.__enter__.return_value.value
        self.response.ok = True
        self.response.text.return_value = "FileLoadComplete"
        self.route = MagicMock()
        self.route.request.post_data_buffer = b'filename="fixture.uhh"'
        self.handler = None
        def register(pattern, handler):
            self.handler = handler
        self.page.route.side_effect = register
        self.control.set_input_files.side_effect = lambda payload: self.handler(self.route)
        self.patches = [patch("reviewer.instrument.importer.ROOT", folder / "python"),
                        patch("reviewer.instrument.importer.validate_file", return_value=dict(sha256=self.sha)),
                        patch("reviewer.instrument.importer.reviewer_status", return_value=dict(indexingEnable=True, freeDiskSize=6, settings_MinFreeDiskSpace=5))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def run_import(self):
        import_single_file(self.page, self.settings, self.sha, False, self.sha, MagicMock())

    def test_single_file_guard_and_journal_prevent_resubmission(self):
        self.run_import()
        self.route.continue_.assert_called_once()
        self.handler(self.route)
        self.route.abort.assert_called_once()
        intent = self.settings.temp / f"import-{self.sha}.json"
        self.assertEqual(json.loads(intent.read_text())["state"], "native-complete")
        with self.assertRaisesRegex(RuntimeError, "previous import attempt"):
            self.run_import()
        self.control.set_input_files.assert_called_once()

    def test_multiple_file_request_is_blocked_and_pending_intent_preserved(self):
        self.route.request.post_data_buffer = b'filename="fixture.uhh" filename="other.uhh"'
        self.route.abort.side_effect = RuntimeError("blocked test transport")
        with self.assertRaisesRegex(RuntimeError, "blocked test transport"):
            self.run_import()
        self.route.continue_.assert_not_called()
        intent = self.settings.temp / f"import-{self.sha}.json"
        self.assertEqual(json.loads(intent.read_text())["state"], "pending")

    def test_incomplete_native_response_is_not_retried(self):
        self.response.text.return_value = "FileLoadCompleteButCorrupted"
        with self.assertRaisesRegex(RuntimeError, "incomplete-data"):
            self.run_import()
        self.control.set_input_files.assert_called_once()
        intent = self.settings.temp / f"import-{self.sha}.json"
        self.assertEqual(json.loads(intent.read_text())["state"], "pending")
