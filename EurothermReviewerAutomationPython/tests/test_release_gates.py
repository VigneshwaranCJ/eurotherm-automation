"""Regression tests for import date gating, single-file inputs, skips, message filtering and environment checks."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, Mock, patch

from reviewer.common.errors import WorkflowError
from reviewer.config import Settings, WORKSPACE
from reviewer.health import environment
from reviewer.instrument.importer import import_single_file
from reviewer.pipeline.calendar import organize
from reviewer.pipeline.configuration import PipelineConfig, inspect_plan
from reviewer.pipeline.inputs import select_folder_input, select_unique_input
from reviewer.pipeline.runner import execute_pipeline
from reviewer.pipeline.state import ProcessingState
from reviewer.ranges import verify_import_interval
from reviewer.reports.messages import classify_messages, parse_alarm, render_csv, write_filtered_messages
from reviewer.ui_runs import RunManager

METADATA = dict(FirstSample="2026-07-23T02:50:07Z", LastSample="2026-07-23T03:45:51Z", Records=[
    dict(kind="SegmentRecord", details=dict(GroupName="Group 6", InstrumentName="SLS-GL-EUT-02")),
    dict(kind="HistoryRecord", details=dict(MacAddr="MAC"))])
GROUP = dict(groupId="g", groupName="Group 6", instrument=dict(instrumentName="SLS-GL-EUT-02", macAddress="MAC"),
             dataStart="2026-07-01T00:00:00", dataEnd="2026-07-20T00:00:00", timezoneOffset=0, daylightSavings=None)


def folder_test(case):
    folder = Path(tempfile.mkdtemp(dir=WORKSPACE))
    case.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    return folder


class ImportDateGateTests(unittest.TestCase):
    def settings(self, mode, start="", end=""):
        return replace(Settings.load({}), range_mode=mode, start=start, end=end)

    def test_dates_outside_the_input_stop_before_import(self):
        settings = self.settings("env", "2026-10-08T00:00:00+01:00", "2026-10-09T00:00:00+01:00")
        with self.assertRaises(WorkflowError) as caught:
            verify_import_interval(Mock(), settings, METADATA, [], Mock())
        self.assertEqual(caught.exception.code, "INTERVAL_OUTSIDE_INPUT")

    def test_dates_overlapping_the_input_are_allowed_and_logged(self):
        log = Mock()
        settings = self.settings("env", "2026-07-23T00:00:00Z", "2026-07-24T00:00:00Z")
        self.assertEqual(verify_import_interval(Mock(), settings, METADATA, [], log)["mode"], "env")
        self.assertEqual(log.call_args.args[0], "importIntervalVerified")

    def test_malformed_dates_stop_before_import(self):
        with self.assertRaises(WorkflowError):
            verify_import_interval(Mock(), self.settings("env", "bad", "bad"), METADATA, [], Mock())

    def test_file_mode_uses_the_input_and_rejects_outside_dates(self):
        self.assertEqual(verify_import_interval(Mock(), self.settings("file"), METADATA, [], Mock())["mode"], "file")
        with self.assertRaises(WorkflowError):
            verify_import_interval(Mock(), self.settings("file", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"), METADATA, [], Mock())

    def test_yesterday_without_a_known_group_cannot_be_verified(self):
        with self.assertRaises(WorkflowError) as caught:
            verify_import_interval(Mock(), self.settings("yesterday"), METADATA, [], Mock())
        self.assertEqual(caught.exception.code, "INTERVAL_UNVERIFIED")

    def test_yesterday_outside_the_input_stops_before_import(self):
        with patch("reviewer.ranges.yesterday_interval", return_value=dict(start="2026-11-01T00:00:00Z", end="2026-11-02T00:00:00Z", mode="yesterday")):
            with self.assertRaises(WorkflowError) as caught:
                verify_import_interval(Mock(), self.settings("yesterday"), METADATA, [GROUP], Mock())
        self.assertEqual(caught.exception.code, "INTERVAL_OUTSIDE_INPUT")

    def test_latest_available_needs_no_requested_dates(self):
        self.assertIsNone(verify_import_interval(Mock(), self.settings("latestAvailable"), METADATA, [], Mock()))

    def pipeline(self, settings):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in (("read_interval", METADATA), ("all_groups", []), ("import_evidence", dict(status="not-imported"))):
            stack.enter_context(patch(f"reviewer.pipeline.runner.{name}", return_value=value))
        importer = stack.enter_context(patch("reviewer.pipeline.runner.import_single_file"))
        config = PipelineConfig(Path("."), Path("."), "", "R", "groupName", (), (), True)
        with self.assertRaises(WorkflowError) as caught:
            execute_pipeline("workflow:run", settings, config, dict(sha="s", token="s"), Mock(), "r", Mock())
        return caught.exception, importer

    def test_workflow_never_imports_when_dates_are_outside_the_input(self):
        error, importer = self.pipeline(self.settings("env", "2026-10-08T00:00:00+01:00", "2026-10-09T00:00:00+01:00"))
        self.assertEqual(error.code, "INTERVAL_OUTSIDE_INPUT")
        importer.assert_not_called()

    def legacy(self, command):
        from reviewer.application.workflow import execute
        stack = ExitStack()
        self.addCleanup(stack.close)
        calls = {name: stack.enter_context(patch(f"reviewer.application.workflow.{name}")) for name in
                 ("inspect_sources", "read_interval", "all_groups", "import_evidence", "import_single_file", "select_group",
                  "check_duplicate", "run_preflight", "inspect_batches", "assert_reviewer_ready", "reviewer_status",
                  "open_chart", "configure_print", "validate_preview", "download_pdf")}
        calls["read_interval"].return_value = METADATA
        calls["import_evidence"].return_value = dict(status="not-imported")
        calls["check_duplicate"].return_value = dict(status="already-imported")
        settings = self.settings("env", "2026-10-08T00:00:00+01:00", "2026-10-09T00:00:00+01:00")
        return calls, lambda: execute(command, settings, dict(sha="s", token="s"), Mock(), "r", Mock())

    def test_full_command_never_imports_when_dates_are_outside_the_input(self):
        calls, run = self.legacy("full")
        with self.assertRaises(WorkflowError):
            run()
        calls["import_single_file"].assert_not_called()

    def test_import_only_command_is_not_blocked_by_report_dates(self):
        calls, run = self.legacy("import:test")
        run()
        calls["import_single_file"].assert_called_once()

    def test_process_block_stops_any_import_even_when_authorized(self):
        settings = replace(Settings.load({}), dry_run=False)
        page = MagicMock()
        with patch.dict(os.environ, REVIEWER_BLOCK_IMPORTS="true"), self.assertRaises(WorkflowError) as caught:
            import_single_file(page, settings, "sha", False, "sha", Mock())
        self.assertEqual(caught.exception.code, "IMPORTS_BLOCKED")
        page.locator.assert_not_called()


class SingleFileAfterOrganizeTests(unittest.TestCase):
    def setUp(self):
        self.root = folder_test(self)
        self.source = self.root / "input.uhh"
        self.source.write_bytes(b"recording")

    def organized(self):
        from datetime import date
        sha = hashlib.sha256(b"recording").hexdigest()
        with patch("reviewer.pipeline.calendar.validate_file", return_value=dict(sha256=sha)):
            return organize(self.source, self.root, date(2026, 8, 30), sha)

    def test_single_file_selection_survives_batch_organize(self):
        target = self.organized()
        self.assertTrue(target.is_file() and target != self.source)
        self.assertEqual(select_unique_input(self.root), self.source)
        self.assertEqual(select_unique_input(self.root, "input.uhh"), self.source)

    def test_workflow_configuration_and_ui_selection_both_survive(self):
        self.organized()
        config = PipelineConfig(self.root, self.root, "input.uhh", "R", "groupName", (), (), True)
        self.assertEqual(config.select_input(), self.source)
        path = self.root / "workflow.json"
        path.write_text(json.dumps(dict(input_dir=str(self.root), input_file="input.uhh")))
        with patch.dict(os.environ, WORKFLOW_CONFIG=str(path)):
            self.assertEqual(select_folder_input(), self.source)

    def test_only_the_organized_copy_remaining_is_still_found(self):
        target = self.organized()
        self.source.unlink()
        self.assertEqual(select_unique_input(self.root), target)

    def test_different_content_is_never_guessed(self):
        target = self.organized()
        target.write_bytes(b"different")
        for filename in ("", "input.uhh"):
            with self.assertRaisesRegex(ValueError, "found 2"):
                select_unique_input(self.root, filename)
        (self.root / "other.uhh").write_bytes(b"other")
        with self.assertRaisesRegex(ValueError, "found 3"):
            select_unique_input(self.root)

    def test_missing_input_still_fails(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            select_unique_input(self.root, "absent.uhh")

    def test_setup_panel_reports_configured_folders_while_mapping_is_incomplete(self):
        path = self.root / "workflow.json"
        inner = self.root / "selected"
        inner.mkdir()
        (inner / "a.uhh").write_bytes(b"a")
        path.write_text(json.dumps(dict(input_dir=str(inner), output_dir=str(self.root / "out"), channels=[])))
        with patch.dict(os.environ, WORKFLOW_CONFIG=str(path)):
            plan = inspect_plan()
        self.assertEqual(plan["inputDirectory"], str(inner))
        self.assertEqual(plan["inputFiles"], ["a.uhh"])
        self.assertFalse(plan["ready"])


CHANNELS = [dict(channelNumber=5, channelName="LS REF-06"), dict(channelNumber=9, channelName="AR HUM"),
            dict(channelNumber=36, channelName="CL Screening REF-13")]
SELECTED = ("LS REF-06", "AR HUM")


def alarm(text, kind=2):
    return dict(content=f"03/11/2026 02:08:20  {text} ", messageType=kind, created="2026-11-02T20:38:20")


class FilteredMessageTests(unittest.TestCase):
    def test_alarm_lines_parse_into_exact_channels(self):
        self.assertEqual(parse_alarm("03/11/2026 02:08:20  Alarm(s) on 5(2) LS REF-06 9(1) AR HUM ")[2],
                         [(5, 2, "LS REF-06"), (9, 1, "AR HUM")])
        for text in ("03/11/2026 02:08:20  (Email) Unable", "03/11/2026 02:08:20  Alarm(s) on LS REF-06",
                     "03/11/2026 02:08:20  Alarm(s) on 5(2) ", "not a message", "", None):
            self.assertIsNone(parse_alarm(text))

    def test_selected_channels_are_kept_and_deselected_ones_removed(self):
        rows, counts = classify_messages([alarm("Alarm(s) on 5(2) LS REF-06 36(2) CL Screening REF-13")], CHANNELS, SELECTED)
        self.assertEqual([r["channelName"] for r in rows], ["LS REF-06"])
        self.assertEqual(rows[0]["otherChannelsRemoved"], 1)
        self.assertEqual(counts["included"], 1)

    def test_a_deselected_only_alarm_is_excluded(self):
        rows, counts = classify_messages([alarm("Alarm(s) off 36(1) CL Screening REF-13")], CHANNELS, SELECTED)
        self.assertEqual(rows, [])
        self.assertEqual(counts["excludedDeselectedOnly"], 1)

    def test_a_selected_name_with_the_wrong_number_is_unreliable(self):
        rows, counts = classify_messages([alarm("Alarm(s) on 77(2) LS REF-06")], CHANNELS, SELECTED)
        self.assertEqual(rows, [])
        self.assertEqual(counts["excludedUnreliable"], 1)

    def test_a_mislabelled_entry_rejects_the_whole_line(self):
        rows, counts = classify_messages([alarm("Alarm(s) on 5(2) LS REF-06 77(2) AR HUM")], CHANNELS, SELECTED)
        self.assertEqual(rows, [])
        self.assertEqual(counts["excludedUnreliable"], 1)

    def test_unparseable_alarms_and_non_alarm_messages_are_excluded(self):
        messages = [alarm("Alarm(s) something LS REF-06"), alarm("Login by LS REF-06", 18), alarm("(Email) Unable", 17),
                    alarm("Ack Alarm ,Signed:operator 5(2) LS REF-06", 19)]
        rows, counts = classify_messages(messages, CHANNELS, SELECTED)
        self.assertEqual(rows, [])
        self.assertEqual((counts["excludedUnreliable"], counts["excludedNoChannel"]), (1, 3))

    def test_no_channel_data_means_nothing_is_reliable(self):
        rows, counts = classify_messages([alarm("Alarm(s) on 5(2) LS REF-06")], [], SELECTED)
        self.assertEqual(rows, [])
        self.assertEqual(counts["excludedUnreliable"], 1)

    def test_csv_is_labelled_on_every_data_row_and_blocks_formulas(self):
        rows = [dict(localTime="t", state="on", channelNumber=1, alarmNumber=1, channelName="=cmd()", messageType=2, createdUtc="c", otherChannelsRemoved=0)]
        text = render_csv(rows, dict(total=1), dict(name="n.pdf", sha256="abc"), "R", "I", dict(start="s", end="e"), SELECTED)
        lines = text.splitlines()
        self.assertIn("NOT A NATIVE", lines[0])
        self.assertTrue(all(line.startswith("# ") for line in lines[:11]))
        self.assertEqual(lines[11].split(",")[0], "source")
        self.assertIn("abc", text)
        self.assertTrue(lines[-1].startswith("SUPPLEMENTARY,"))
        self.assertIn("'=cmd()", lines[-1])

    def test_native_pdf_bytes_are_never_changed(self):
        folder = folder_test(self)
        pdf = folder / "native.pdf"
        pdf.write_bytes(b"%PDF-native")
        evidence = write_filtered_messages(dict(output=str(pdf), messageTimestamps=1), [alarm("Alarm(s) on 5(2) LS REF-06")],
                                           CHANNELS, SELECTED, GROUP, dict(start="s", end="e"), Mock())
        self.assertEqual(pdf.read_bytes(), b"%PDF-native")
        self.assertTrue(Path(evidence["output"]).name.startswith("SUPPLEMENTARY_"))
        self.assertEqual(evidence["sha256"], hashlib.sha256(Path(evidence["output"]).read_bytes()).hexdigest())

    def test_a_tampered_list_invalidates_its_checkpoint(self):
        from reviewer.pipeline.journal import ExportJournal
        folder = folder_test(self)
        pdf, extra = folder / "native.pdf", folder / "extra.csv"
        pdf.write_bytes(b"%PDF")
        extra.write_bytes(b"list")
        journal = ExportJournal(folder / "journal", dict(a=1))
        journal.commit("message-log", dict(output=str(pdf), supplementary=dict(output=str(extra), sha256=hashlib.sha256(b"list").hexdigest())))
        self.assertIsNotNone(journal.cached("message-log"))
        extra.write_bytes(b"changed")
        self.assertIsNone(journal.cached("message-log"))


SKIP = dict(status="SKIPPED_NO_MESSAGES", profile="message-log", date="2026-11-03", instrument="I", reason="None")


class NoMessageRecordingTests(unittest.TestCase):
    def outputs(self, folder, names):
        result = []
        for name in names:
            path = folder / name
            path.write_bytes(name.encode())
            result.append(dict(output=str(path), sha256=hashlib.sha256(name.encode()).hexdigest()))
        return result

    def test_batch_completes_a_day_with_two_reports_and_one_skip(self):
        folder = folder_test(self)
        self.assertTrue(ProcessingState.verified(self.outputs(folder, ["a.pdf", "b.pdf"]) + [SKIP]))

    def test_skip_cannot_replace_a_chart_report_or_hide_a_missing_file(self):
        folder = folder_test(self)
        reports = self.outputs(folder, ["a.pdf", "b.pdf"])
        self.assertFalse(ProcessingState.verified(reports + [dict(SKIP, profile="graph")]))
        self.assertFalse(ProcessingState.verified(reports[:1] + [SKIP, SKIP]))
        self.assertFalse(ProcessingState.verified(reports))
        Path(reports[0]["output"]).unlink()
        self.assertFalse(ProcessingState.verified(reports + [SKIP]))

    def test_batch_continues_to_the_next_day_after_a_skip(self):
        from reviewer.pipeline.batch import run_batch
        folder = folder_test(self)
        source = folder / "source.uhh"
        source.write_bytes(b"source")
        sha = hashlib.sha256(b"source").hexdigest()
        config = PipelineConfig(folder, folder / "output", "", "R", "groupName", (), (), True)
        tasks = [dict(date=f"2026-10-1{i}", start=f"2026-10-1{i}T00:00:00.000Z", end=f"2026-10-1{i}T12:00:00.000Z") for i in (3, 4)]
        record = dict(source=str(source), sha256=sha, status="Pending", tasks=tasks)
        days = []
        def native(command, daily, authorization, pipeline_config, on_event):
            days.append(daily.recording_date)
            reports = self.outputs(folder, [f"{daily.recording_date}-a.pdf", f"{daily.recording_date}-b.pdf"])
            on_event("profileStarted", dict(profile="message-log"))
            on_event("messageLogSkipped", dict(SKIP, date=daily.recording_date))
            return reports + [dict(SKIP, date=daily.recording_date)]
        settings = replace(Settings.load({}), temp=folder / "temp", logs=folder / "logs")
        with patch("reviewer.pipeline.batch.roots", return_value=(folder, config.output_dir)), patch("reviewer.pipeline.batch.STATUS", folder / "status.json"), \
                patch("reviewer.pipeline.batch.DATABASE", folder / "state.sqlite"), patch("reviewer.pipeline.batch.PipelineConfig.load", return_value=config), \
                patch("reviewer.pipeline.batch.scan", return_value=[record]), patch("reviewer.application.run.run_command", side_effect=native):
            result = run_batch(settings, "batch:run")
        self.assertEqual(days, ["2026-10-13", "2026-10-14"])
        self.assertEqual((result["status"], result["completedFiles"], result["failedFiles"]), ("Completed", 1, 0))
        self.assertEqual(result["skippedReports"], 2)
        self.assertEqual(result["profiles"]["message-log"], "SKIPPED_NO_MESSAGES")

    def test_web_status_shows_the_skip_for_a_message_only_run(self):
        folder = folder_test(self)
        manager = RunManager(SimpleSettings(folder))
        manager.save(dict(id="ui-1", status="Success", action="workflow:messages", message="done", output=None))
        manager.save(dict(id="ui-2", status="Success", action="workflow:run", message="done", output=None))
        line = json.dumps(dict(event="messageLogSkipped", data=SKIP)) + "\n"
        for job in ("ui-1", "ui-2"):
            (manager.folder / f"{job}.log").write_text(line, encoding="utf-8")
        jobs = {job["id"]: job for job in manager.records()[0]}
        self.assertEqual(jobs["ui-1"]["status"], "SKIPPED_NO_MESSAGES")
        self.assertIn("2026-11-03", jobs["ui-1"]["message"])
        self.assertEqual(jobs["ui-2"]["status"], "Success")  # The other reports in this run succeeded.
        self.assertIn("SKIPPED_NO_MESSAGES", jobs["ui-2"]["message"])


class SimpleSettings:
    def __init__(self, logs):
        self.logs = logs


class EnvironmentTests(unittest.TestCase):
    def test_runtime_list_requires_dotnet_10(self):
        self.assertEqual(environment.dotnet_10_versions("Microsoft.NETCore.App 8.0.1 [x]\nMicrosoft.NETCore.App 10.0.14 [x]\n"), ["10.0.14"])
        self.assertEqual(environment.dotnet_10_versions("Microsoft.AspNetCore.App 10.0.1 [x]\nMicrosoft.NETCore.App 8.0.1 [x]\n"), [])

    def test_missing_dotnet_is_reported_with_the_install_command(self):
        with patch("reviewer.health.environment.shutil.which", return_value=None):
            passed, detail = environment.check_dotnet()
        self.assertFalse(passed)
        self.assertIn("winget install Microsoft.DotNet.Runtime.10", detail)

    def test_only_older_dotnet_fails(self):
        with patch("reviewer.health.environment.shutil.which", return_value=r"C:\Program Files\dotnet\dotnet.exe"), \
                patch("reviewer.health.environment.subprocess.run", return_value=Mock(stdout="Microsoft.NETCore.App 8.0.1 [x]\n")):
            self.assertFalse(environment.check_dotnet()[0])

    def test_permanent_dotnet_10_passes_and_temporary_fails(self):
        for path, expected in ((r"C:\Program Files\dotnet\dotnet.exe", True), (r"C:\Users\A\AppData\Local\Temp\x\dotnet.exe", False)):
            with patch("reviewer.health.environment.shutil.which", return_value=path), \
                    patch("reviewer.health.environment.subprocess.run", return_value=Mock(stdout="Microsoft.NETCore.App 10.0.14 [x]\n")):
                self.assertEqual(environment.check_dotnet()[0], expected)

    def test_temporary_python_locations_are_rejected(self):
        for path in (r"C:\Users\A\.cache\codex-runtimes\x\python", r"C:\Users\A\AppData\Local\Temp\x"):
            self.assertTrue(environment.is_temporary(path))
        self.assertFalse(environment.is_temporary(r"C:\Users\A\AppData\Local\Programs\Python\Python312"))
        with patch("reviewer.health.environment.sys.base_prefix", r"C:\Users\A\.cache\codex-runtimes\python"):
            self.assertFalse(environment.check_python()[0])

    def test_report_fails_when_any_check_fails(self):
        with patch("builtins.print"):
            self.assertTrue(environment.print_environment_report(dict(a=(True, "ok"))))
            self.assertFalse(environment.print_environment_report(dict(a=(True, "ok"), b=(False, "no"))))

    def test_missing_dotnet_gives_a_clear_metadata_error(self):
        from reviewer.instrument.metadata import read_interval
        with patch("reviewer.instrument.metadata.subprocess.check_output", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(RuntimeError, "NET 10"):
                read_interval(Settings.load({}))


APP = b"""<!doctype html><title>Import stub</title><button id="testAuto_topMenu_importUHHFiles">Import</button>
<input id="dropfilehere" type="file">
<script>document.querySelector('#dropfilehere').onchange = e => { const form = new FormData();
for (const f of e.target.files) form.append('file', f); fetch('/api/imports/progress', {method:'POST', body:form}); };</script>"""


class ImportEndpoint(BaseHTTPRequestHandler):
    bodies, reply = [], b"FileLoadComplete"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(APP)))
        self.end_headers()
        self.wfile.write(APP)

    def do_POST(self):
        type(self).bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.reply)))
        self.end_headers()
        self.wfile.write(self.reply)


class ImportIntegrationTests(unittest.TestCase):
    """The real importer and upload guard in real Chrome over real HTTP. It never contacts Reviewer."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        if not environment.check_chrome()[0]:
            raise unittest.SkipTest("Google Chrome is not installed")
        cls.scratch = tempfile.mkdtemp(dir=WORKSPACE)
        cls.environment = patch.dict(os.environ, TEMP=cls.scratch, TMP=cls.scratch)
        cls.environment.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ImportEndpoint)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.environment.stop()
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def setUp(self):
        ImportEndpoint.bodies = []
        ImportEndpoint.reply = b"FileLoadComplete"
        self.folder = folder_test(self)
        self.file = self.folder / "fixture.uhh"
        self.file.write_bytes(b"test payload, never sent to Reviewer")
        self.sha = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.settings = replace(Settings.load({}), file=self.file, temp=self.folder, logs=self.folder, dry_run=False)
        for target, value in (("ROOT", self.folder / "python"), ("validate_file", Mock(return_value=dict(sha256=self.sha))),
                              ("reviewer_status", Mock(return_value=dict(indexingEnable=True, freeDiskSize=6, settings_MinFreeDiskSpace=5)))):
            active = patch(f"reviewer.instrument.importer.{target}", value)
            active.start()
            self.addCleanup(active.stop)
        block = patch.dict(os.environ)
        block.start()
        self.addCleanup(block.stop)
        os.environ.pop("REVIEWER_BLOCK_IMPORTS", None)
        context = self.browser.new_context()
        self.addCleanup(context.close)
        self.page = context.new_page()
        self.page.goto(f"http://127.0.0.1:{self.server.server_port}/")

    def run_import(self):
        import_single_file(self.page, self.settings, self.sha, False, self.sha, Mock())

    def test_individual_file_is_submitted_once_with_a_journal(self):
        self.run_import()
        self.assertEqual(len(ImportEndpoint.bodies), 1)
        self.assertIn(b'filename="fixture.uhh"', ImportEndpoint.bodies[0])
        self.assertIn(self.file.read_bytes(), ImportEndpoint.bodies[0])
        intent = json.loads((self.folder / f"import-{self.sha}.json").read_text())
        self.assertEqual(intent["state"], "native-complete")

    def test_second_attempt_is_refused_without_a_new_request(self):
        self.run_import()
        with self.assertRaisesRegex(RuntimeError, "previous import attempt"):
            self.run_import()
        self.assertEqual(len(ImportEndpoint.bodies), 1)

    def test_incomplete_native_result_keeps_the_attempt_pending(self):
        ImportEndpoint.reply = b"FileLoadCompleteButCorrupted"
        with self.assertRaisesRegex(RuntimeError, "incomplete-data"):
            self.run_import()
        self.assertEqual(json.loads((self.folder / f"import-{self.sha}.json").read_text())["state"], "pending")

    def test_process_block_sends_nothing(self):
        with patch.dict(os.environ, REVIEWER_BLOCK_IMPORTS="true"), self.assertRaises(WorkflowError):
            self.run_import()
        self.assertEqual(ImportEndpoint.bodies, [])
        self.assertFalse((self.folder / f"import-{self.sha}.json").exists())


if __name__ == "__main__":
    unittest.main()
