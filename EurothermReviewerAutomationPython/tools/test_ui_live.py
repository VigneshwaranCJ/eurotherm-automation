"""Drive the compiled web UI against the real API and CLI. Refuses to run unless imports are blocked.

Usage, with REVIEWER_BLOCK_IMPORTS=true set in the environment:
    python tools/test_ui_live.py <screenshot-folder> <command=ExpectedStatus> ...
Workflow settings come from the environment (WORKFLOW_CONFIG, REPORT_MODE and report dates).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
BUTTONS = {"batch:scan": "Scan files", "batch:organize": "Organize by date", "batch:run": "Start automation"}


def history():
    with urlopen(BASE + "/api/history", timeout=30) as response:
        return json.load(response)


def run_action(page, command, expected, folder):
    known = {record["id"] for record in history()["records"]}
    if command in BUTTONS:
        page.get_by_role("button", name=BUTTONS[command], exact=True).click()
    else:
        page.get_by_label("Automation action").select_option(command)
        page.get_by_role("button", name="Run automation", exact=True).click()
    started, record = time.monotonic(), None
    while time.monotonic() - started < 1500:
        fresh = [r for r in history()["records"] if r["id"] not in known and r["action"] == command]
        if fresh and fresh[0]["status"] != "Running":
            record = fresh[0]
            break
        time.sleep(2)
    if record is None:
        raise TimeoutError(f"{command} did not finish")
    badge = page.locator(f".status-{record['status'].lower()}").first
    expect(badge).to_be_visible(timeout=10000)
    page.screenshot(path=str(Path(folder) / f"{command.replace(':', '-')}.png"), full_page=True)
    outputs = record.get("outputs") or []
    links = []
    for artifact in outputs:
        if artifact.get("url"):
            with urlopen(BASE + artifact["url"], timeout=60) as response:
                links.append((Path(artifact["path"]).suffix, response.read(5)))
    with urlopen(BASE + record["logUrl"], timeout=30) as response:
        has_log = bool(response.read())
    # Every listed output must really download, and each PDF must really be a PDF.
    passed = (record["status"] == expected and has_log and len(links) == len(outputs)
              and all(head == b"%PDF-" for suffix, head in links if suffix == ".pdf"))
    print(json.dumps(dict(result="PASS" if passed else "FAIL", command=command, expected=expected, status=record["status"],
                          exitCode=record.get("exitCode"), outputs=[Path(a["path"]).name for a in outputs],
                          links=[suffix for suffix, _ in links], message=str(record.get("message"))[:220])), flush=True)
    return passed


def main():
    if os.environ.get("REVIEWER_BLOCK_IMPORTS", "").lower() != "true":
        raise SystemExit("Set REVIEWER_BLOCK_IMPORTS=true; this test must not be able to import.")
    folder, actions = sys.argv[1], [item.split("=", 1) for item in sys.argv[2:]]
    Path(folder).mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "reviewer.web"], cwd=ROOT, env=dict(os.environ, HEADLESS="true"),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    passed = True
    try:
        for _ in range(60):
            try:
                history()
                break
            except OSError:
                time.sleep(.5)
        else:
            raise RuntimeError("The web UI did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport=dict(width=1280, height=900))
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(BASE)
                expect(page.get_by_text("System connected")).to_be_visible(timeout=30000)
                for command, expected in actions:
                    expect(page.get_by_role("button", name="Run automation", exact=True)).to_be_enabled(timeout=30000)
                    passed = run_action(page, command, expected, folder) and passed
                if errors:
                    print("Browser errors:", errors)
                    passed = False
            finally:
                browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
