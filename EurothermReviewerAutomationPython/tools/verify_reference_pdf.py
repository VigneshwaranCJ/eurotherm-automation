"""Check a preserved native PDF using identity/channel evidence from its original run.

This is an offline content check, not a new live native report. The fixture's
instrument offset (+01:00) is explicit, independent of the PDF's printed text.
"""
from datetime import timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pypdf import PdfReader
from reviewer.config import Settings
from reviewer.core import utc_time
from reviewer.reporting import verify_text


def main():
    from dataclasses import replace
    reference = ROOT.parent / "EurothermReviewerAutomation"
    log = reference / "logs" / "2026-10-09T08-10-18-312Z.jsonl"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    def data(event):
        return next(r["data"] for r in records if r["event"] == event)
    original = data("pdfVerified")
    chart = data("chart")
    group = data("groupMatched")
    group["groupName"] = group["name"]
    def display(stamp):
        wall = utc_time(stamp) + timedelta(hours=1)
        return wall.strftime("%H:%M:%S.") + f"{wall.microsecond // 1000:03d} " + wall.strftime("%d/%m/%Y +01:00")
    chart.update(displayStart=display(chart["start"]), displayEnd=display(chart["end"]))
    chart["channels"] = [dict(channelName=c["name"]) for c in chart["channels"]]
    settings = replace(Settings.load({"REPORT_MODE": "latestAvailable"}), title=data("start")["reportTitle"])
    path = Path(original["output"])
    document = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in document.pages)
    verify_text(text, group, chart, settings)
    if len(document.pages) != original["pages"] or len(chart["channels"]) != original["channelCount"]:
        raise RuntimeError("PDF page/channel counts differ from the original verified report")
    result = dict(source=str(path), originalEvidence=str(log), pages=len(document.pages),
                  channelCount=len(chart["channels"]), titleVerified=True, identityVerified=True,
                  exactBoundariesVerified=True, readableValuesVerified=True, newLiveReport=False)
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "offline-pdf-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
