"""Data Sources is diagnostic: an empty page warns instead of stopping the run."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from reviewer.ui.sources import inspect_sources


class DataSourcesTests(unittest.TestCase):
    def run_with(self, page):
        events = []
        with tempfile.TemporaryDirectory() as folder:
            result = inspect_sources(page, SimpleNamespace(screenshots=Path(folder)), lambda e, d=None: events.append((e, d)), "run")
        return result, dict(events)

    def test_an_empty_data_sources_page_warns_and_continues(self):
        page = MagicMock()
        page.wait_for_function.side_effect = PlaywrightTimeout("Timeout 30000ms exceeded")
        result, events = self.run_with(page)
        self.assertEqual(result, [])
        self.assertEqual(events["preflightWarning"]["code"], "DATA_SOURCES_UNAVAILABLE")
        self.assertNotIn("dataSources", events)

    def test_listed_instruments_are_returned(self):
        page = MagicMock()
        cards = [dict(name="SLS-GL-EUT-02", lastFileTransfer="2026-11-17T17:20:00+05:30")]
        page.locator.return_value.evaluate_all.return_value = cards
        page.locator.return_value.inner_text.return_value = "Last file transfer"
        result, events = self.run_with(page)
        self.assertEqual(result, cards)
        self.assertNotIn("preflightWarning", events)

    def test_other_errors_still_stop_the_run(self):
        page = MagicMock()
        page.wait_for_function.side_effect = RuntimeError("browser closed")
        with self.assertRaisesRegex(RuntimeError, "browser closed"):
            self.run_with(page)


if __name__ == "__main__":
    unittest.main()
