"""Behavioral coverage of the reference's command, safety and reporting contracts."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from reviewer.config import ROOT, Settings, inside_root
from reviewer.core import COMMANDS, WorkflowError, run_lock, should_import, should_download, utc_time
from reviewer.ranges import configured_interval, file_interval, latest_available, overlaps, require_data
from reviewer.reporting import verify_boundaries, verify_text, set_custom_check
from reviewer.uhh import assert_import_authorized, check_duplicate, import_evidence, select_group

META = dict(FirstSample="2026-07-23T02:50:07.5Z", LastSample="2026-07-23T03:45:51.125Z", Records=[
    dict(kind="SegmentRecord", details=dict(GroupName="Group 6", InstrumentName="SLS-GL-EUT-02")),
    dict(kind="HistoryRecord", details=dict(MacAddr="000A8D823E81")),
])
GROUP = dict(groupId="id", groupName="Group 6", instrument=dict(instrumentName="SLS-GL-EUT-02", macAddress="000A8D823E81"),
             dataStart="2026-07-07T09:20:15", dataEnd="2026-08-01T10:13:52.5")
READY = dict(indexingEnable=True, freeDiskSize=6, settings_MinFreeDiskSpace=5)
CHART = dict(displayStart="10:58:52.500 01/08/2026 +01:00", displayEnd="11:13:52.500 01/08/2026 +01:00", channels=[dict(channelName="Channel A")])


class PolicyTests(unittest.TestCase):
    def test_import_policy_for_every_command(self):
        for command in COMMANDS:
            self.assertFalse(should_import(command, "already-imported"))
            self.assertEqual(should_import(command, "missing"), command in {"import:test", "full"})

    def test_download_policy_for_every_command(self):
        for command in COMMANDS:
            self.assertEqual(should_download(command, True), command == "report")
            self.assertEqual(should_download(command, False), command in {"report", "full"})

    def test_import_authorization(self):
        for dry, token, uncertain in [(True, "abc", False), (False, "abc", True), (False, "other", False)]:
            with self.subTest(dry=dry, token=token, uncertain=uncertain), self.assertRaises(RuntimeError):
                assert_import_authorized(dry, token, "abc", uncertain)
        assert_import_authorized(False, "abc", "abc", False)

    def test_group_identity_and_ambiguity(self):
        wrong = dict(GROUP, instrument=dict(GROUP["instrument"], instrumentName="Instrument"))
        self.assertIs(select_group([wrong, GROUP], META), GROUP)
        for groups in ([GROUP, dict(GROUP)], [wrong]):
            with self.assertRaisesRegex(RuntimeError, "candidates"):
                select_group(groups, META)
        with self.assertRaisesRegex(RuntimeError, "Configured group"):
            select_group([GROUP], META, "Other")

    def test_archive_match_and_collision(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            file, archive = Path(folder) / "source.uhh", Path(folder) / "archive.uhh"
            file.write_bytes(b"data")
            with patch("reviewer.instrument.duplicates.archived_file", return_value=archive):
                self.assertEqual(check_duplicate(GROUP, file)["status"], "uncertain")
                archive.write_bytes(b"data")
                self.assertEqual(check_duplicate(GROUP, file)["status"], "already-imported")
                archive.write_bytes(b"different")
                with self.assertRaisesRegex(RuntimeError, "collision"):
                    check_duplicate(GROUP, file)

    def test_overlap_is_uncertain_and_never_auto_imports(self):
        with patch("reviewer.instrument.duplicates.check_duplicate", return_value=dict(status="uncertain")):
            self.assertEqual(import_evidence([GROUP], META, Path("test.uhh"))["status"], "uncertain")
            self.assertEqual(import_evidence([], META, Path("test.uhh"))["status"], "not-imported")

    def test_output_paths_stay_in_workspace(self):
        for path in (r"C:\outside\report.pdf", ROOT.parent / ".." / "outside.pdf"):
            with self.assertRaisesRegex(ValueError, "remain under"):
                inside_root(path)

    def test_invalid_configuration(self):
        for key, value in [("REPORT_CHART_WIDTH_PAGES", "NaN"), ("REPORT_MAJOR_DIVISIONS", "-1"),
                           ("REPORT_MINOR_DIVISIONS", "0"), ("SOURCE_TRANSFER_STALE_MINUTES", "Infinity"),
                           ("REPORT_PAPER_SIZE", "unknown"), ("REPORT_SAMPLE_INTERVAL", "Automatic"),
                           ("REVIEWER_URL", "http://localhost/#/groups"), ("REPORT_MODE", "unknown")]:
            with self.subTest(key=key), self.assertRaises((ValueError, OverflowError)):
                Settings.load({key: value})

    def test_historical_title(self):
        self.assertIn("HISTORICAL TEST REPORT", Settings.load({"REPORT_MODE": "latestAvailable"}).title)

    def test_run_lock_blocks_overlap_and_releases_on_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            filename = Path(folder) / "automation.lock"
            with self.assertRaisesRegex(RuntimeError, "forced"):
                with run_lock(filename):
                    with self.assertRaisesRegex(RuntimeError, "Another run"):
                        with run_lock(filename):
                            pass
                    raise RuntimeError("forced")
            self.assertFalse(filename.exists())
            with run_lock(filename):
                self.assertTrue(filename.exists())

    def test_missing_lock_directory_is_not_overlap(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            with self.assertRaises(FileNotFoundError):
                with run_lock(Path(folder) / "missing" / "automation.lock"):
                    pass


class RangeTests(unittest.TestCase):
    def test_exact_env_instants(self):
        result = configured_interval("2026-10-08T00:00:00+01:00", "2026-10-09T00:00:00+01:00")
        self.assertEqual(result["start"], "2026-10-07T23:00:00.000Z")
        self.assertEqual(result["end"], "2026-10-08T23:00:00.000Z")

    def test_invalid_dates_and_reversed_ranges(self):
        end = "2026-10-09T00:00:00+01:00"
        for start in ("", "08/10/2026 00:00", "2026-10-08T00:00:00", "2026-02-30T00:00:00+01:00", "2026-10-08T24:00:00+01:00", end):
            with self.subTest(start=start), self.assertRaises(WorkflowError) as error:
                configured_interval(start, end)
            self.assertEqual(error.exception.code, "INVALID_INTERVAL")

    def test_missing_data_never_falls_back(self):
        interval = configured_interval("2026-10-08T00:00:00+01:00", "2026-10-09T00:00:00+01:00")
        self.assertFalse(overlaps(GROUP, interval))
        with self.assertRaises(WorkflowError) as error:
            require_data(GROUP, interval)
        self.assertEqual(error.exception.code, "MISSING_DATA")
        self.assertEqual(interval["mode"], "env")

    def test_missing_data_says_which_side_does_not_overlap(self):
        from reviewer.ranges import describe_gap
        record = dict(groupName="SLS733(EUT-01)", dataStart="2025-12-25T05:50:00", dataEnd="2026-11-15T04:34:00",
                      timezoneOffset=19800000)
        after = describe_gap(record, configured_interval("2026-11-16T00:00:00+05:30", "2026-11-17T00:00:00+05:30"))
        self.assertIn("Requested 16/11/2026 00:00 to 17/11/2026 00:00", after)
        self.assertIn("has data from 25/12/2025 11:20 to 15/11/2026 10:04 (UTC+05:30)", after)
        self.assertIn("after the last data: it starts 13 h 56 min after", after)
        before = describe_gap(record, configured_interval("2025-12-20T00:00:00+05:30", "2025-12-24T00:00:00+05:30"))
        self.assertIn("before the first data: it ends 1 d 11 h 20 min before", before)
        with self.assertRaisesRegex(WorkflowError, "starts 13 h 56 min after"):
            require_data(record, configured_interval("2026-11-16T00:00:00+05:30", "2026-11-17T00:00:00+05:30"))

    def test_dst_day_rejected(self):
        with self.assertRaises(WorkflowError) as error:
            require_data(GROUP, dict(start="2026-08-01T00:00:00Z", end="2026-08-01T23:00:00Z", mode="yesterday"))
        self.assertEqual(error.exception.code, "INVALID_INTERVAL")

    def test_historical_range_is_bounded(self):
        interval = latest_available(GROUP)
        self.assertEqual(interval["end"], "2026-08-01T10:13:52.500Z")
        self.assertEqual((utc_time(interval["end"]) - utc_time(interval["start"])).total_seconds(), 900)
        self.assertTrue(interval["historical"])
        require_data(GROUP, interval)
        short = latest_available(dict(dataStart="2026-08-01T10:13:00", dataEnd="2026-08-01T10:13:52.5"))
        self.assertEqual(short["start"], "2026-08-01T10:13:00.000Z")
        with self.assertRaises(WorkflowError):
            latest_available(dict(dataStart="invalid", dataEnd="invalid"))

    def test_touching_ranges_do_not_overlap(self):
        self.assertFalse(overlaps(dict(dataStart="2026-07-01T00:00:00", dataEnd="2026-10-07T23:00:00"),
                                  dict(start="2026-10-07T23:00:00Z", end="2026-10-08T23:00:00Z")))

    def test_file_interval_stays_inside_uhh(self):
        self.assertEqual(file_interval(META)["start"], META["FirstSample"])
        for start, end in [("2026-07-22T00:00:00Z", None), (None, "2026-07-24T00:00:00Z")]:
            with self.assertRaises(WorkflowError):
                file_interval(META, start, end)


class ReadinessAndReportTests(unittest.TestCase):
    def test_windows_service_query_preserves_display_name_matching(self):
        from reviewer.diagnostics import parse_services
        output = "SERVICE_NAME: ES8\nDISPLAY_NAME: Elasticsearch\n STATE : 4 RUNNING\nSERVICE_NAME: ReviewerClientServices\nDISPLAY_NAME: Client\n STATE : 1 STOPPED\nSERVICE_NAME: Other\nDISPLAY_NAME: Unrelated\n STATE : 4 RUNNING\n"
        self.assertEqual(parse_services(output), [dict(name="ES8", status="Running"), dict(name="ReviewerClientServices", status="Stopped")])

    def test_distinct_disk_and_indexing_failures(self):
        from reviewer.diagnostics import readiness_issues, assert_reviewer_ready
        self.assertEqual(readiness_issues(READY), [])
        self.assertEqual([i["code"] for i in readiness_issues(dict(READY, indexingEnable=False, freeDiskSize=4))], ["LOW_DISK_SPACE", "INDEXING_DISABLED"])
        self.assertEqual(readiness_issues(READY, [dict(drive="C:\\", freeGB=4)])[0]["code"], "LOW_DISK_SPACE")
        self.assertEqual(readiness_issues(dict(READY, settings_MinFreeDiskSpace=None))[0]["code"], "STATUS_UNAVAILABLE")
        with self.assertRaises(WorkflowError):
            assert_reviewer_ready(dict(indexingEnable=False))

    def test_boundary_times_and_dates_are_required(self):
        verify_boundaries("10:58:52.500\n01/08/2026 footer 11:13:52.500 01/08/2026", CHART)
        for text in ("01/08/2026 10:58:52.500 01/08/2026", "10:57:52.500 01/08/2026 11:13:52.500 01/08/2026"):
            with self.assertRaisesRegex(RuntimeError, "time and recording date"):
                verify_boundaries(text, CHART)

    def test_pdf_identity_values_channels_and_boundaries(self):
        settings = Settings.load({"REPORT_MODE": "file"})
        text = f"Instrument: SLS-GL-EUT-02, Group: Group 6\n{settings.title} Channel A Cursor statistics 1.25 10:58:52.500 01/08/2026 11:13:52.500 01/08/2026"
        verify_text(text, GROUP, CHART, settings)
        for removed in (settings.title, "SLS-GL-EUT-02", "Channel A", "Cursor statistics", "1.25", "10:58:52.500"):
            changed = text.replace(removed, "")
            if removed == "1.25":
                # Boundary fractions are numeric too; separately check a values-only report.
                changed = "Group 6 SLS-GL-EUT-02 Channel A Cursor statistics " + settings.title
            with self.subTest(removed=removed), self.assertRaises(RuntimeError):
                verify_text(changed, GROUP, CHART, settings)

    def test_browser_closes_on_initialization_failure(self):
        from reviewer.browser import open_reviewer
        browser = MagicMock()
        browser.new_context.return_value.new_page.return_value.wait_for_function.side_effect = RuntimeError("initialization failed")
        with patch("reviewer.ui.browser.sync_playwright") as mocked:
            mocked.return_value.__enter__.return_value.chromium.launch.return_value = browser
            with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                with open_reviewer(Settings.load({})):
                    pass
        browser.close.assert_called_once()

    def test_checkbox_state_rejection_fails(self):
        locator = MagicMock()
        locator.locator.return_value.count.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "checkbox"):
            set_custom_check(locator, True)


if __name__ == "__main__":
    unittest.main()
