"""Exercise orchestration with a ready Reviewer and all preflight failure paths.

Browser/service calls are mocked here; live behavior is recorded separately by
tools/compare_projects.py. These tests must never upload instrument files.
"""
from contextlib import ExitStack
from dataclasses import replace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from reviewer.config import Settings
from reviewer.core import WorkflowError
from reviewer.workflow import execute


class WorkflowTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.calls = {}
        for name in ("inspect_sources", "read_interval", "all_groups", "import_evidence", "import_single_file",
                     "select_group", "check_duplicate", "configured_interval", "run_preflight", "inspect_batches",
                     "assert_reviewer_ready", "reviewer_status", "open_chart", "configure_print", "validate_preview", "download_pdf"):
            self.calls[name] = self.stack.enter_context(patch(f"reviewer.application.workflow.{name}"))
        self.calls["import_evidence"].return_value = dict(status="already-imported")
        self.calls["select_group"].return_value = dict(groupId="id", groupName="Group 6", instrument={}, dataStart="start", dataEnd="end")
        self.calls["check_duplicate"].return_value = dict(status="already-imported")
        self.settings = Settings.load({"REPORT_MODE": "latestAvailable", "DRY_RUN": "true"})
        self.log = MagicMock()

    def run_command(self, command, settings=None):
        execute(command, settings or self.settings, dict(sha="sha", token=None), self.log, "test", MagicMock())

    def test_report_downloads_after_verified_preview_even_when_dry_run(self):
        self.run_command("report")
        self.calls["configure_print"].assert_called_once()
        self.calls["validate_preview"].assert_called_once()
        self.calls["download_pdf"].assert_called_once()
        self.calls["import_single_file"].assert_not_called()

    def test_dry_preview_never_downloads(self):
        self.run_command("report:dry")
        self.calls["validate_preview"].assert_called_once()
        self.calls["download_pdf"].assert_not_called()
        self.calls["import_single_file"].assert_not_called()

    def test_full_dry_run_skips_existing_import_and_download(self):
        self.run_command("full")
        self.calls["import_single_file"].assert_not_called()
        self.calls["validate_preview"].assert_called_once()
        self.calls["download_pdf"].assert_not_called()

    def test_full_nondry_downloads_existing_import(self):
        self.run_command("full", replace(self.settings, dry_run=False))
        self.calls["download_pdf"].assert_called_once()
        self.calls["import_single_file"].assert_not_called()

    def test_diagnostics_stops_before_chart(self):
        self.run_command("diagnostics")
        self.calls["run_preflight"].assert_called_once()
        self.calls["open_chart"].assert_not_called()
        self.calls["download_pdf"].assert_not_called()

    def test_archive_duplicate_skips_import_and_preflight(self):
        self.run_command("import:test")
        self.calls["import_single_file"].assert_not_called()
        self.calls["run_preflight"].assert_not_called()
        self.log.assert_any_call("importSkipped", dict(reason="Exact archived content already exists"))

    def test_unverified_import_blocks_reporting(self):
        self.calls["check_duplicate"].return_value = dict(status="uncertain")
        with self.assertRaisesRegex(RuntimeError, "unverified import"):
            self.run_command("report")
        self.calls["run_preflight"].assert_not_called()
        self.calls["download_pdf"].assert_not_called()

    def test_preflight_failure_blocks_chart_and_download(self):
        self.calls["run_preflight"].side_effect = WorkflowError("LOW_DISK_SPACE", "Reporting preflight failed")
        with self.assertRaises(WorkflowError):
            self.run_command("report")
        self.calls["open_chart"].assert_not_called()
        self.calls["download_pdf"].assert_not_called()

    def test_preview_failure_blocks_download(self):
        self.calls["validate_preview"].side_effect = WorkflowError("PREVIEW_FAILED", "Wrong recording boundaries")
        with self.assertRaises(WorkflowError):
            self.run_command("report")
        self.calls["download_pdf"].assert_not_called()

    def test_import_failure_never_retries(self):
        self.calls["import_evidence"].return_value = dict(status="not-imported")
        self.calls["import_single_file"].side_effect = RuntimeError("Not authorized")
        with self.assertRaisesRegex(RuntimeError, "Not authorized"):
            self.run_command("import:test")
        self.calls["import_single_file"].assert_called_once()
        self.calls["download_pdf"].assert_not_called()
