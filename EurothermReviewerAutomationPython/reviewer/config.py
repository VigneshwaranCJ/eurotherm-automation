"""Configuration matching the reference with project-local runtime paths."""
from dataclasses import dataclass
import math
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent


def inside_root(value):
    path = Path(value).resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError(f"Path must remain under {WORKSPACE}: {value}")
    return path


@dataclass(frozen=True)
class Settings:
    url: str
    sources_url: str
    file: Path
    reports: Path
    downloads: Path
    screenshots: Path
    logs: Path
    temp: Path
    headless: bool
    channel: str
    dry_run: bool
    tls_exception: bool
    title: str
    paper: str
    range_mode: str
    stale_minutes: float
    include_values: bool
    include_chart: bool
    include_messages: bool
    separate_messages: bool
    cursor_statistics: bool
    pages: int
    major: int
    minor: int
    group: str
    batch: str
    start: str
    end: str
    recording_date: str = ''
    source_key: str = ''
    report_name: str = ''

    @classmethod
    def load(cls, env=None):
        values = dict(dotenv_values(ROOT / ".env"))
        values.update(os.environ if env is None else env)
        def get(key, default=""):
            return values.get(key) or default
        def flag(key, default="false"):
            value = get(key, default)
            if value not in {"true", "false"}:
                raise ValueError(f"{key} must be true or false")
            return value == "true"
        def output(key, fallback):
            return inside_root(get(key, str(fallback)))
        def positive(key, default):
            value = float(get(key, str(default)))
            if not value.is_integer() or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
            return int(value)
        mode = get("REPORT_MODE", get("REPORT_RANGE_MODE", "yesterday"))
        if mode == "previous-day":
            mode = "yesterday"
        if mode not in {"yesterday", "env", "latestAvailable", "file"}:
            raise ValueError("REPORT_MODE must be yesterday, env, latestAvailable or file")
        title = get("REPORT_TITLE", "Eurotherm Data Report")
        if mode == "latestAvailable":
            title += " — HISTORICAL TEST REPORT"
        paper = get("REPORT_PAPER_SIZE", "A4")
        if paper not in {"A4", "A3", "Letter", "Ledger"}:
            raise ValueError("Unsupported REPORT_PAPER_SIZE")
        if get("REPORT_SAMPLE_INTERVAL", "Raw Data") != "Raw Data":
            raise ValueError("Only the verified Raw Data report sample interval is supported")
        stale = float(get("SOURCE_TRANSFER_STALE_MINUTES", "120"))
        if not math.isfinite(stale) or stale <= 0:
            raise ValueError("SOURCE_TRANSFER_STALE_MINUTES must be finite and positive")
        url = get("REVIEWER_URL", "https://localhost/#/groups")
        sources_url = get("DATA_SOURCES_URL", "https://localhost/#/datasources")
        for candidate in (url, sources_url):
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or parsed.hostname != "localhost":
                raise ValueError("Only HTTPS localhost Reviewer is allowed")
        return cls(
            url, sources_url,
            output("TEST_UHH_FILE", WORKSPACE / "uhh_files" / "Group-6~20260723_823E8130050002A0.uhh"),
            output("REPORT_OUTPUT_DIR", WORKSPACE / "downloads"),
            output("DOWNLOAD_DIR", WORKSPACE / "downloads"),
            output("SCREENSHOT_DIR", ROOT / "screenshots"),
            output("LOG_DIR", ROOT / "logs"), output("TEMP_DIR", ROOT / ".tmp"),
            flag("HEADLESS"), values.get("BROWSER_CHANNEL", "chrome"),
            flag("DRY_RUN", "true"), flag("ALLOW_LOCALHOST_TLS_EXCEPTION"),
            title, paper, mode, stale,
            flag("REPORT_INCLUDE_VALUES", "true"), flag("REPORT_INCLUDE_CHART", "true"),
            flag("REPORT_INCLUDE_MESSAGES", "true"), flag("REPORT_SHOW_MESSAGES_SEPARATELY", "true"),
            flag("REPORT_SHOW_CURSOR_STATISTICS", "true"),
            positive("REPORT_CHART_WIDTH_PAGES", 1), positive("REPORT_MAJOR_DIVISIONS", 10),
            positive("REPORT_MINOR_DIVISIONS", 50), get("GROUP_NAME"), get("BATCH_NAME"),
            get("START_DATETIME"), get("END_DATETIME"),
        )

    def prepare(self):
        for folder in (self.reports, self.downloads, self.screenshots, self.logs, self.temp):
            folder.mkdir(parents=True, exist_ok=True)
        os.environ.update(TEMP=str(self.temp), TMP=str(self.temp))
