"""Channels Logs, Pen Logs and Message Logs: validators plus Chrome/PDF integration, including failures."""
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from reviewer.config import Settings, WORKSPACE
from reviewer.pipeline.configuration import PipelineConfig
from reviewer.pipeline.runner import execute_pipeline
from reviewer.pipeline.selection import validate_channels
from reviewer.reports.validation import (preview_page_total, verify_date_range, verify_identity, verify_page_count,
                                         verify_text)
from reviewer.ui.groups import all_groups, group_card
from reviewer_stub import CHANNELS, DESELECTED, END, INSTRUMENT, RECORDS, SELECTED, START, ReviewerStub, api_messages, report_html

COMMANDS = {"Channels Logs": ("workflow:channels", "graph"), "Pen Logs": ("workflow:pen", "pen-log"),
            "Message Logs": ("workflow:messages", "message-log")}
METADATA = dict(FirstSample="2026-11-02T13:44:00Z", LastSample="2026-11-04T04:18:00Z", Records=[
    dict(kind="SegmentRecord", details=dict(GroupName="Group 1", InstrumentName=INSTRUMENT["instrumentName"])),
    dict(kind="HistoryRecord", details=dict(MacAddr=INSTRUMENT["macAddress"]))])
INTERVAL = dict(start=START, end=END, mode="env", historical=False)
GROUP = dict(groupName="SLS733(EUT-01)", instrument=INSTRUMENT, isCustomGroup=True)
CHART = dict(displayStart="00:00:00.000 03/11/2026 +05:30", displayEnd="00:00:00.000 04/11/2026 +05:30",
             channels=[dict(channelName=n) for n in SELECTED], deselectedChannels=DESELECTED)


def profile(chart=True, values=False, messages=False, cursor=True, title="report"):
    return SimpleNamespace(title=title, include_chart=chart, include_values=values, include_messages=messages,
                           separate_messages=messages, cursor_statistics=cursor, pages=1)


class CustomRecordChannelTests(unittest.TestCase):
    mappings = [dict(name=n) for n in SELECTED]

    def sampled(self, names=CHANNELS):
        return [dict(channelName=n, dataPoints=[1]) for n in names]

    def test_record_with_more_than_25_channels_is_accepted(self):
        self.assertEqual(len(validate_channels(self.sampled(), self.mappings)), 35)

    def test_exactly_25_approved_channels_are_required(self):
        import json
        with tempfile.TemporaryDirectory(dir=WORKSPACE) as folder:
            path = Path(folder) / "workflow.json"
            for mappings in (self.mappings[:-1], self.mappings + [dict(name=CHANNELS[30])]):
                path.write_text(json.dumps(dict(record_id="SLS733(EUT-01)", record_field="groupName", channels=mappings)))
                with self.subTest(count=len(mappings)), self.assertRaisesRegex(ValueError, "Exactly 25"):
                    PipelineConfig.load(path)
        for mappings in ([self.mappings[0]] * 25, []):
            with self.subTest(count=len(mappings)), self.assertRaisesRegex(ValueError, "unique and non-empty"):
                validate_channels(self.sampled(), mappings)

    def test_split_by_channel_accepts_every_record_channel(self):
        import json
        with tempfile.TemporaryDirectory(dir=WORKSPACE) as folder:
            path = Path(folder) / "workflow.json"
            base = dict(record_id="SLS733(EUT-01)", record_field="groupName", split_by_channel=True)
            path.write_text(json.dumps(dict(base, channels=[dict(name=n) for n in CHANNELS])))
            config = PipelineConfig.load(path)
            self.assertTrue(config.split_by_channel)
            self.assertEqual(len(config.channels), 35)
            self.assertEqual(config.summary()["reportsPerRun"], 105)
            self.assertEqual(len(validate_channels(self.sampled(), config.channels)), 35)
            for bad, message in ((dict(base, channels=[]), "1 to 100"),
                                 (dict(base, channels=[dict(name="ULTF-01")] * 2), "unique"),
                                 (dict(base, channels=[dict(name="ULTF-01")], split_by_channel="yes"), "boolean"),
                                 (dict(base, channels=[dict(name="ULTF-01")], graph_channels=["CH-02"]), "all 1 approved")):
                path.write_text(json.dumps(bad))
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    PipelineConfig.load(path)

    def test_combined_configurations_keep_their_checkpoint_identity(self):
        config = PipelineConfig(Path("."), Path("."), "", "R", "groupName", (), (), True)
        self.assertNotIn("split_by_channel", config.identity())
        self.assertNotIn("splitByChannel", config.summary())
        self.assertTrue(replace(config, split_by_channel=True).identity()["split_by_channel"])

    def test_missing_ambiguous_and_empty_selected_channels_fail(self):
        with self.assertRaisesRegex(ValueError, "missing=\\['ULTF-01'\\]"):
            validate_channels(self.sampled(CHANNELS[1:]), self.mappings)
        with self.assertRaisesRegex(ValueError, "ambiguous=\\['ULTF-01'\\]"):
            validate_channels(self.sampled(CHANNELS + ["ULTF-01"]), self.mappings)
        empty = [dict(channel, dataPoints=[] if channel["channelName"] == "ULTF-01" else [1]) for channel in self.sampled()]
        with self.assertRaisesRegex(ValueError, "without samples"):
            validate_channels(empty, self.mappings)

    def test_an_empty_deselected_channel_does_not_block_the_report(self):
        channels = [dict(c, dataPoints=[] if c["channelName"] == DESELECTED[0] else [1]) for c in self.sampled()]
        self.assertEqual(len(validate_channels(channels, self.mappings)), 35)

    def test_configuration_needs_no_selector_and_old_files_still_load(self):
        with tempfile.TemporaryDirectory(dir=WORKSPACE) as folder:
            path = Path(folder) / "workflow.json"
            import json
            for channels in (self.mappings, [dict(m, selector="#old") for m in self.mappings]):
                path.write_text(json.dumps(dict(record_id="SLS733(EUT-01)", record_field="groupName", channels=channels)))
                self.assertEqual(len(PipelineConfig.load(path).channels), 25)


class ReportValidatorTests(unittest.TestCase):
    def test_identity_is_exact_rather_than_a_substring(self):
        good = "Instrument: SLS-GL-EUT-01, Group: SLS733(EUT-01)\nreport"
        verify_identity(good, GROUP, profile())
        for text in ("Instrument: SLS-GL-EUT-01, Group: SLS733(EUT-01)X\nreport",
                     "Instrument: SLS-GL-EUT-02, Group: SLS733(EUT-01)\nreport",
                     "Instrument: SLS-GL-EUT-01, Group: EUT-01\nreport", "SLS-GL-EUT-01 SLS733(EUT-01) report"):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                verify_identity(text, GROUP, profile())

    def test_virtual_instrument_is_only_allowed_on_custom_message_reports(self):
        text = "Instrument: Virtual Instrument, Group: SLS733(EUT-01)\nreport"
        verify_identity(text, GROUP, profile(chart=False, messages=True))
        for group, settings in ((GROUP, profile()), (dict(GROUP, isCustomGroup=False), profile(chart=False, messages=True))):
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                verify_identity(text, group, settings)

    def test_timestamps_outside_the_range_fail(self):
        verify_date_range("03/11/2026 02:08:20 Alarm 00:00:00.000 04/11/2026 Time of print: 11:35:55 06/11/2026 00:00:00.000 04/11/2026", CHART)
        for text in ("02/11/2026 23:59:59 Alarm", "04/11/2026 00:00:01 Alarm", "00:00:00.001 04/11/2026"):
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, "outside the requested range"):
                verify_date_range(text, CHART)

    def test_print_time_is_not_mistaken_for_report_data(self):
        evidence = verify_date_range("Time of print: 11:10:04 06/11/2026 00:00:00.000 04/11/2026", CHART)
        self.assertEqual(evidence["messageTimestamps"], 0)

    def test_page_count_comes_from_complete_footers_not_page_check(self):
        page = "Instrument: A, Group: B\n{}"
        settings = profile()
        verify_page_count([page.format("1/2"), page.format("Chart Speed: fit to 1 pages 2/2")], settings, 2)
        for pages, preview, message in (
                ([page.format("1/3"), page.format("2/3")], None, "numbering"),
                ([page.format("1/2"), page.format("1/2")], None, "numbering"),
                ([page.format("1/2"), page.format("no footer")], None, "without a page-number"),
                ([page.format("1/1")], None, "at least 2"),
                ([page.format("1/2"), page.format("2/2")], 3, "Preview had 3"),
                (["1/2", page.format("2/2")], None, "lack the instrument"),
                ([], None, "no pages")):
            with self.subTest(pages=pages), self.assertRaisesRegex(RuntimeError, message):
                verify_page_count(pages, settings, preview)

    def test_preview_total_uses_the_final_footer(self):
        self.assertEqual(preview_page_total("a\n1/23\nb\nChart Speed: fit to 1 pages\n23/23"), 23)
        for text in ("no footer", "1/23\nb\n22/23"):
            with self.assertRaises(RuntimeError):
                preview_page_total(text)

    def test_channel_names_are_not_matched_inside_longer_names(self):
        text = "Instrument: SLS-GL-EUT-01, Group: SLS733(EUT-01)\nreport Cursor statistics ULTF-010 00:00:00.000 03/11/2026 00:00:00.000 04/11/2026"
        chart = dict(CHART, channels=[dict(channelName="ULTF-01")], deselectedChannels=[])
        with self.assertRaisesRegex(RuntimeError, "missing channels"):
            verify_text(text, GROUP, chart, profile())


class ScenarioIntegrationTests(unittest.TestCase):
    """Run the real pipeline in Chrome against the stub. Only instrument and health checks are replaced."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        if not any(Path(root, "Google", "Chrome", "Application", "chrome.exe").is_file()
                   for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LOCALAPPDATA", ""))):
            raise unittest.SkipTest("Google Chrome is not installed")
        # Other tests can leave TEMP pointing at a removed folder, which would stop Chrome starting.
        cls.scratch = tempfile.mkdtemp(dir=WORKSPACE)
        cls.environment = patch.dict(os.environ, TEMP=cls.scratch, TMP=cls.scratch)
        cls.environment.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.environment.stop()
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(dir=WORKSPACE))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        channels = tuple(dict(name=n) for n in SELECTED)
        self.config = PipelineConfig(self.folder, self.folder / "output", "", "SLS733(EUT-01)", "groupName", channels, tuple(SELECTED), True)
        self.settings = replace(Settings.load({}), logs=self.folder / "logs", screenshots=self.folder / "shots",
                                temp=self.folder / "temp", range_mode="env", start=START, end=END, paper="A4",
                                pages=1, major=10, minor=50, recording_date="")
        for path in (self.settings.logs, self.settings.screenshots):
            path.mkdir()

    def pdf(self, html):
        if html not in self.cache:
            page = self.browser.new_page()
            page.set_content(html)
            self.cache[html] = page.pdf(format="A4")
            page.close()
        return self.cache[html]

    def run_scenario(self, name, pdf_html=None, preview_html=None, config=None, channels=None, messages=None, **stub):
        """Return (results, events); pdf_html and preview_html replace the correct report with a faulty one."""
        command, key = COMMANDS[name]
        good = report_html(key)
        pdfs = {key: self.pdf(pdf_html or good)}
        context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(context.close)
        page = context.new_page()
        self.stub = ReviewerStub(page, pdfs, {key: preview_html or good}, channels=channels, messages=messages, **stub)
        events = []
        log = lambda event, data=None: events.append((event, data))
        patches = {"read_interval": METADATA, "import_evidence": dict(status="already-imported"),
                   "select_group": dict(groupId="id-group"), "check_duplicate": dict(status="already-imported"),
                   "inspect_sources": [], "run_preflight": INTERVAL}
        active = [patch(f"reviewer.pipeline.runner.{target}", return_value=value) for target, value in patches.items()]
        importer = patch("reviewer.pipeline.runner.import_single_file")
        mocks = [p.start() for p in active]
        forbidden = importer.start()
        for item in active + [importer]:
            self.addCleanup(item.stop)
        try:
            results = execute_pipeline(command, self.settings, config or self.config, dict(sha="sha", token=None), log, "run", page)
        finally:
            forbidden.assert_not_called()
            self.events = events
        return results, events

    def published(self):
        return list((self.folder / "output").rglob("*.pdf"))

    def assert_rejected(self, name, message, **arguments):
        with self.assertRaisesRegex(Exception, message):
            self.run_scenario(name, **arguments)
        self.assertEqual(self.published(), [], "A rejected report must not be published")

    # --- All three scenarios succeed end to end ---

    def assert_success(self, name, pages, warned):
        results, events = self.run_scenario(name)
        result = results[0]
        self.assertTrue(Path(result["output"]).is_file())
        self.assertEqual(result["pages"], pages)
        selected = dict(events)["channelsSelected"]
        self.assertEqual(selected["selected"], SELECTED)
        self.assertEqual(selected["deselected"], DESELECTED)
        self.assertEqual(selected["clicks"], 10)
        self.assertEqual(dict(events)["preview"]["pages"], pages)
        self.assertEqual("messageScopeWarning" in dict(events), warned)
        self.assertEqual(result["deselectedChannelsInMessages"], DESELECTED[:2] if warned else [])
        return result, dict(events)

    def test_channels_logs_exports_chart_and_cursor_for_selected_channels(self):
        _, events = self.assert_success("Channels Logs", 2, warned=False)
        accepted = events["printSettings"]
        self.assertEqual((accepted["includeChart"], accepted["includeValues"], accepted["includeMessages"], accepted["includeCursorStats"]),
                         (True, False, False, True))

    def test_pen_logs_exports_all_include_options(self):
        _, events = self.assert_success("Pen Logs", 4, warned=True)
        accepted = events["printSettings"]
        self.assertTrue(all(accepted[k] for k in ("includeChart", "includeValues", "includeMessages", "includeMessagesSeperately", "includeCursorStats")))

    def test_message_logs_exports_with_charts_and_values_off(self):
        result, events = self.assert_success("Message Logs", 1, warned=True)
        accepted = events["printSettings"]
        self.assertEqual((accepted["includeChart"], accepted["includeValues"], accepted["includeMessages"]), (False, False, True))
        self.assertNotIn("fitToPages", accepted)
        self.assertEqual(result["messageTimestamps"], 3)

    # --- Navigation and record identity ---

    def test_reviewer_remembering_the_custom_tab_does_not_stall_navigation(self):
        self.run_scenario("Channels Logs", remembered_tab="custom")
        self.assertIn("/api/groups/custom/filters", self.stub.requests)

    def test_overlapping_record_names_each_open_their_own_card(self):
        page = self.browser.new_context().new_page()
        ReviewerStub(page, {})
        records = all_groups(page, custom=True)
        self.assertEqual({r["groupName"] for r in records}, {r["groupName"] for r in RECORDS})
        for current in records:
            with self.subTest(record=current["groupName"]):
                self.assertEqual(group_card(page, current).count(), 1)
                self.assertTrue(group_card(page, current).inner_text().startswith(current["groupName"] + " ["))
        with self.assertRaises(Exception):
            group_card(page, dict(records[0], groupId="absent", groupName="absent")).click(timeout=100)
        page.context.close()

    def test_exact_eut_01_record_is_selected_from_overlapping_names(self):
        config = replace(self.config, record_id="EUT-01")
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):  # The stub's report belongs to SLS733(EUT-01).
            self.run_scenario("Channels Logs", config=config, preview_html=report_html("graph", title="EUT-01 - graph"))
        self.assertEqual(dict(self.events)["customRecordSelected"]["groupId"], "id-eut")

    def test_ambiguous_or_absent_records_fail(self):
        self.assert_rejected("Channels Logs", "found 0", config=replace(self.config, record_id="EUT-0"))

    def test_chart_opening_a_different_record_fails(self):
        self.assert_rejected("Channels Logs", "instead of the selected record", wrongChart=True)

    # --- Channel control failures ---

    def test_show_hide_channel_click_not_accepted_fails(self):
        for name, channel in (("Channels Logs", DESELECTED[0]), ("Pen Logs", DESELECTED[1]), ("Message Logs", DESELECTED[2])):
            with self.subTest(name):
                self.assert_rejected(name, "did not accept", ignoreToggle=[channel])

    def test_selected_channel_without_samples_fails(self):
        self.assert_rejected("Pen Logs", "without samples", channels=lambda n: [] if n == "ULTF-01" else [1, 2])

    # --- Report content failures for each scenario ---

    def test_wrong_group_in_exported_pdf_fails(self):
        for name, key in (("Channels Logs", "graph"), ("Pen Logs", "pen-log"), ("Message Logs", "message-log")):
            with self.subTest(name):
                self.assert_rejected(name, "identity mismatch", pdf_html=report_html(key, group="EUT-01"))

    def test_wrong_instrument_fails(self):
        self.assert_rejected("Channels Logs", "identity mismatch", pdf_html=report_html("graph", instrument="SLS-GL-EUT-02"))
        self.assert_rejected("Message Logs", "identity mismatch", pdf_html=report_html("message-log", instrument="SLS-GL-EUT-02"))

    def test_truncated_or_unnumbered_pdf_fails(self):
        self.assert_rejected("Pen Logs", "numbering", pdf_html=report_html("pen-log", claimed_total=5))
        self.assert_rejected("Channels Logs", "page-number", pdf_html=report_html("graph", no_footer=True))

    def test_pdf_page_total_must_match_its_preview(self):
        sections = report_html("pen-log", claimed_total=3).split("<section")
        preview = "<section".join(sections[:4])  # Drop the fourth page; the Preview now claims 3/3.
        self.assert_rejected("Pen Logs", "Preview had 3", preview_html=preview)

    def test_message_logs_without_a_messages_section_fail(self):
        self.assert_rejected("Message Logs", "message section", pdf_html=report_html("message-log", no_heading=True))

    def test_message_outside_the_date_range_fails(self):
        self.assert_rejected("Message Logs", "outside the requested range", pdf_html=report_html("message-log", message_day="05/11/2026"))

    def test_wrong_report_boundaries_fail_for_all_scenarios(self):
        for name, key in (("Channels Logs", "graph"), ("Pen Logs", "pen-log"), ("Message Logs", "message-log")):
            with self.subTest(name):
                self.assert_rejected(name, "start time|outside the requested range", pdf_html=report_html(key, start="00:00:00.000 02/11/2026"))

    def test_deselected_channel_data_fails(self):
        self.assert_rejected("Pen Logs", "deselected channel data", pdf_html=report_html("pen-log", extra_columns=[DESELECTED[0]]))
        self.assert_rejected("Channels Logs", "deselected channel", pdf_html=report_html("graph", graph_mentions_deselected=True))

    def test_blank_preview_when_messages_exist_is_a_failure_not_a_skip(self):
        with patch("reviewer.reports.preview.MESSAGE_PREVIEW_TIMEOUT", 1500):
            self.assert_rejected("Message Logs", "rendered no Message Logs preview", blankPreview=True)
        self.assertNotIn("/download.pdf", self.stub.requests)

    # --- No-message days ---

    def test_no_message_day_is_skipped_without_a_pdf(self):
        results, events = self.run_scenario("Message Logs", messages=[])
        self.assertEqual(results[0]["status"], "SKIPPED_NO_MESSAGES")
        self.assertEqual(self.published(), [])
        self.assertEqual(list((self.folder / "output").rglob("*.csv")), [])
        self.assertNotIn("/download.pdf", self.stub.requests)
        skipped = dict(events)["messageLogSkipped"]
        self.assertEqual(skipped["instrument"], INSTRUMENT["instrumentName"])
        self.assertEqual(skipped["date"], "2026-11-03")  # Local report date, not the UTC start's 2026-11-02.
        self.assertIn("no messages", skipped["reason"])

    def test_no_message_day_lets_the_other_reports_complete(self):
        pdfs = {key: self.pdf(report_html(key)) for key in ("graph", "pen-log")}
        previews = {key: report_html(key) for key in ("graph", "pen-log")}
        context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(context.close)
        page = context.new_page()
        ReviewerStub(page, pdfs, previews, messages=[])
        events = []
        with patch("reviewer.pipeline.runner.read_interval", return_value=METADATA), \
                patch("reviewer.pipeline.runner.import_evidence", return_value=dict(status="already-imported")), \
                patch("reviewer.pipeline.runner.select_group", return_value=dict(groupId="id-group")), \
                patch("reviewer.pipeline.runner.check_duplicate", return_value=dict(status="already-imported")), \
                patch("reviewer.pipeline.runner.inspect_sources", return_value=[]), \
                patch("reviewer.pipeline.runner.run_preflight", return_value=INTERVAL):
            results = execute_pipeline("workflow:run", self.settings, self.config, dict(sha="sha", token=None),
                                       lambda event, data=None: events.append((event, data)), "run", page)
        self.assertEqual([r.get("status") for r in results], [None, None, "SKIPPED_NO_MESSAGES"])
        self.assertEqual(len(self.published()), 2)
        self.assertEqual(dict(events)["workflowComplete"]["skipped"], ["message-log"])

    def test_one_command_writes_all_three_logs_into_one_folder(self):
        keys = ("graph", "pen-log", "message-log")
        pdfs = {key: self.pdf(report_html(key)) for key in keys}
        previews = {key: report_html(key) for key in keys}
        context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(context.close)
        page = context.new_page()
        ReviewerStub(page, pdfs, previews)

        def run(command, run_id):
            with patch("reviewer.pipeline.runner.read_interval", return_value=METADATA), \
                    patch("reviewer.pipeline.runner.import_evidence", return_value=dict(status="already-imported")), \
                    patch("reviewer.pipeline.runner.select_group", return_value=dict(groupId="id-group")), \
                    patch("reviewer.pipeline.runner.check_duplicate", return_value=dict(status="already-imported")), \
                    patch("reviewer.pipeline.runner.inspect_sources", return_value=[]), \
                    patch("reviewer.pipeline.runner.run_preflight", return_value=INTERVAL):
                return execute_pipeline(command, self.settings, self.config, dict(sha="sha", token=None),
                                        lambda event, data=None: None, run_id, page)

        # An earlier single command's report joins the set instead of being left elsewhere.
        first = run("workflow:channels", "run-1")
        results = run("workflow:run", "run-2")
        self.assertEqual(results[0]["output"], first[0]["output"])
        outputs = [Path(r["output"]) for r in results]
        self.assertEqual([p.parent.name for p in outputs], ["channel", "pen", "message"])
        self.assertEqual(len({p.parent.parent for p in outputs}), 1)
        self.assertEqual(outputs[0].parent.parent.name, "run-1")
        self.assertEqual(Path(results[2]["supplementary"]["output"]).parent, outputs[2].parent)
        # A rerun reuses the same files and creates no new folder.
        again = run("workflow:run", "run-3")
        self.assertEqual([r["output"] for r in again], [str(p) for p in outputs])
        self.assertFalse(list((self.folder / "output").rglob("run-2")) + list((self.folder / "output").rglob("run-3")))

    # --- One PDF per channel ---

    def run_split(self, names, messages=None, run_id="run"):
        """Run workflow:run with split_by_channel; the stub serves a distinct report for each single channel."""
        keys = ("graph", "pen-log", "message-log")
        htmls = {f"{key}|{name}": report_html(key, selected=[name], deselected=[n for n in CHANNELS if n != name])
                 for key in keys for name in names}
        if not hasattr(self, "split_page"):
            context = self.browser.new_context(accept_downloads=True)
            self.addCleanup(context.close)
            self.split_page = context.new_page()
            self.split_stub = ReviewerStub(self.split_page, {k: self.pdf(v) for k, v in htmls.items()}, htmls, messages=messages)
        config = replace(self.config, channels=tuple(dict(name=n) for n in names), graph_channels=tuple(names), split_by_channel=True)
        events = self.split_events = []
        with patch("reviewer.pipeline.runner.read_interval", return_value=METADATA), \
                patch("reviewer.pipeline.runner.import_evidence", return_value=dict(status="already-imported")), \
                patch("reviewer.pipeline.runner.select_group", return_value=dict(groupId="id-group")), \
                patch("reviewer.pipeline.runner.check_duplicate", return_value=dict(status="already-imported")), \
                patch("reviewer.pipeline.runner.inspect_sources", return_value=[]), \
                patch("reviewer.pipeline.runner.run_preflight", return_value=INTERVAL):
            results = execute_pipeline("workflow:run", self.settings, config, dict(sha="sha", token=None),
                                       lambda event, data=None: events.append((event, data)), run_id, self.split_page)
        return results, events

    def test_split_by_channel_writes_one_pdf_per_channel_and_type(self):
        names = ["ULTF-01", "CH-02", "CH-03"]
        results, events = self.run_split(names)
        outputs = [Path(r["output"]) for r in results]
        self.assertEqual(len(outputs), 9)
        self.assertEqual(len({p.parent.parent for p in outputs}), 1)
        expected = ["01_ULTF-01.pdf", "02_CH-02.pdf", "03_CH-03.pdf"]
        for folder in ("channel", "pen", "message"):
            self.assertEqual(sorted(p.name for p in outputs if p.parent.name == folder), expected)
        self.assertEqual([r["channel"] for r in results], names * 3)
        # Every report showed exactly its own channel.
        selections = [data["selected"] for event, data in events if event == "channelsSelected"]
        self.assertEqual(selections, [[n] for n in names] * 3)
        from reviewer.reports.validation import channel_present
        for result in results[:6]:  # Channel and pen PDFs carry chart data; message PDFs do not.
            output = Path(result["output"])
            text = (self.settings.logs / f"{output.parent.name}_{output.name}.txt").read_text(encoding="utf-8")
            self.assertTrue(channel_present(result["channel"], text))
            if Path(result["output"]).parent.name == "channel":  # No messages, so no other channel may appear.
                self.assertEqual([n for n in CHANNELS if channel_present(n, text)], [result["channel"]])
        # One filtered message list per channel, beside its message PDF.
        csvs = sorted(Path(r["supplementary"]["output"]).name for r in results[6:])
        self.assertEqual(csvs, [f"SUPPLEMENTARY_filtered_messages_{Path(n).stem}.csv" for n in expected])
        self.assertEqual([r["supplementary"]["included"] for r in results[6:]], [2, 1, 0])
        self.assertEqual(sum(1 for e, _ in events if e == "channelReportComplete"), 9)
        self.assertEqual([d["profile"] for e, d in events if e == "profileComplete"], ["graph", "pen-log", "message-log"])
        # A rerun reuses all nine verified files without downloading again.
        downloads = self.split_stub.requests.count("/download.pdf")
        again, _ = self.run_split(names, run_id="run-2")
        self.assertEqual([r["output"] for r in again], [str(p) for p in outputs])
        self.assertEqual(self.split_stub.requests.count("/download.pdf"), downloads)

    def test_split_by_channel_resumes_after_an_interrupted_channel(self):
        names = ["ULTF-01", "CH-02"]
        original = execute_pipeline.__globals__["download_pdf"]
        calls = []

        def failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("interrupted")
            return original(*args, **kwargs)
        with patch("reviewer.pipeline.runner.download_pdf", side_effect=failing):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.run_split(names)
        done = sorted(p.relative_to(self.folder / "output") for p in self.published())
        self.assertEqual([p.parent.name + "/" + p.name for p in done], ["channel/01_ULTF-01.pdf", "channel/02_CH-02.pdf"])
        results, events = self.run_split(names, run_id="run-2")
        self.assertEqual(len(results), 6)
        self.assertEqual(sum(1 for e, d in events if e == "pdfVerified" and d.get("reused")), 2)
        self.assertEqual(len({Path(r["output"]).parent.parent for r in results}), 1)

    def test_a_reviewer_timeout_is_retried_once_but_a_failed_check_is_not(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from reviewer.common.errors import WorkflowError
        original = execute_pipeline.__globals__["validate_preview"]

        def flaky(fail_on, error):
            calls = []

            def preview(*args, **kwargs):
                calls.append(1)
                if len(calls) in fail_on:
                    raise error
                return original(*args, **kwargs)
            return preview

        def timeout():
            try:
                raise PlaywrightTimeout("Timeout 120000ms exceeded")
            except PlaywrightTimeout as cause:
                failure = WorkflowError("PREVIEW_FAILED", "Timeout 120000ms exceeded")
                failure.__cause__ = cause
                return failure
        with patch("reviewer.pipeline.runner.validate_preview", side_effect=flaky({2}, timeout())):
            results, events = self.run_split(["ULTF-01", "CH-02"])
        self.assertEqual(len(results), 6)
        retries = [d for e, d in events if e == "reportRetry"]
        self.assertEqual([(d["profile"], d["channel"]) for d in retries], [("graph", "CH-02")])
        with patch("reviewer.pipeline.runner.validate_preview", side_effect=flaky({1}, WorkflowError("PREVIEW_FAILED", "Report is missing channels"))):
            with self.assertRaisesRegex(WorkflowError, "missing channels"):
                self.run_split(["CH-03"], run_id="run-check")
        self.assertFalse(any(e == "reportRetry" for e, _ in self.events_of_last_split()))
        with patch("reviewer.pipeline.runner.validate_preview", side_effect=flaky({1, 2}, timeout())):
            with self.assertRaisesRegex(WorkflowError, "Timeout"):
                self.run_split(["CH-04"], run_id="run-twice")

    def events_of_last_split(self):
        return getattr(self, "split_events", [])

    def test_split_by_channel_without_messages_skips_once_and_keeps_the_rest(self):
        results, events = self.run_split(["ULTF-01", "CH-02"], messages=[])
        self.assertEqual([r.get("status") for r in results], [None] * 4 + ["SKIPPED_NO_MESSAGES"])
        self.assertEqual(sum(1 for e, _ in events if e == "messageLogSkipped"), 1)
        self.assertFalse(any(p.parent.name == "message" for p in self.published()))
        self.assertEqual([d["profile"] for e, d in events if e == "profileComplete"], ["graph", "pen-log"])

    # --- Supplementary filtered messages ---

    def test_native_pdf_is_unchanged_and_the_list_is_separate_and_labelled(self):
        results, events = self.run_scenario("Message Logs")
        native = Path(results[0]["output"])
        self.assertEqual(native.read_bytes(), self.pdf(report_html("message-log")))
        extra = Path(results[0]["supplementary"]["output"])
        self.assertTrue(extra.name.startswith("SUPPLEMENTARY_"))
        self.assertEqual(extra.suffix, ".csv")
        self.assertNotEqual(extra, native)
        self.assertFalse(results[0]["supplementary"]["native"])
        text = extra.read_text(encoding="utf-8-sig")
        self.assertIn("NOT A NATIVE EUROTHERM REVIEWER REPORT", text.splitlines()[0])
        self.assertIn(results[0]["supplementary"]["nativeReport"]["sha256"], text)
        for name in SELECTED[:2]:
            self.assertIn(name, text)
        for name in DESELECTED:
            self.assertNotIn(name, text)
        self.assertNotIn("Login", text)
        self.assertEqual(results[0]["supplementary"]["included"], 2)
        self.assertEqual(results[0]["supplementary"]["excludedNoChannel"], 1)
        self.assertIn("messageScopeWarning", dict(events))  # The warning about the native PDF stays.

    def test_list_is_withheld_when_message_data_disagrees_with_the_pdf(self):
        results, events = self.run_scenario("Message Logs", messages=api_messages()[:2])
        self.assertIsNone(results[0]["supplementary"])
        self.assertTrue(Path(results[0]["output"]).is_file())
        self.assertIn("supplementaryMessagesWithheld", dict(events))
        self.assertEqual(list((self.folder / "output").rglob("*.csv")), [])

    def test_only_message_logs_produce_a_supplementary_list(self):
        for name in ("Channels Logs", "Pen Logs"):
            with self.subTest(name):
                results, _ = self.run_scenario(name)
                self.assertNotIn("supplementary", results[0])
        self.assertEqual(list((self.folder / "output").rglob("*.csv")), [])

    def test_preview_failure_prevents_any_download(self):
        self.assert_rejected("Message Logs", "identity mismatch", preview_html=report_html("message-log", group="EUT-01"))
        self.assertNotIn("/download.pdf", self.stub.requests)


if __name__ == "__main__":
    unittest.main()
