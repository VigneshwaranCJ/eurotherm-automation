"""Small local server for the Report Runner page.

It serves index.html, style.css and app.js, and starts the existing command
`python -m reviewer workflow:run` with the dates chosen on the page.
Imports into Reviewer stay blocked (REVIEWER_BLOCK_IMPORTS=true).
Only this PC can reach it: it listens on 127.0.0.1.

The run is started as its own process and its details are saved in runs/current.json,
so closing or restarting this server does not stop a run, and the page picks it up again.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = Path(r"D:\Ceiyone\EurothermReviewerAutomationPython")
PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
CONFIG = PROJECT / ".tmp" / "e2e" / "r5" / "wf-split.json"
LOCK = PROJECT / ".tmp" / "automation.lock"
OFFSET = "+05:30"  # The instrument records in IST.
HOST, PORT = "127.0.0.1", 8780
RUNS = HERE / "runs"
CURRENT = RUNS / "current.json"
FILES = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
         "/style.css": ("style.css", "text/css"), "/app.js": ("app.js", "text/javascript")}
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
PROFILE_NAMES = {"graph": "Channel log", "pen-log": "Pen log", "message-log": "Message log"}

sys.path.insert(0, str(PROJECT))
from reviewer.pipeline.recovery import owner_active  # noqa: E402  (the project's own process check)

state_lock = threading.Lock()


def load_run():
    try:
        return json.loads(CURRENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_run(run):
    RUNS.mkdir(exist_ok=True)
    temporary = CURRENT.with_suffix(".tmp")
    temporary.write_text(json.dumps(run, indent=2), encoding="utf-8")
    temporary.replace(CURRENT)


def expected_reports():
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        channels = len(config.get("channels", []))
        return channels * 3 if config.get("split_by_channel") else 3, channels
    except (OSError, ValueError):
        return 0, 0


def lock_state():
    """'none', 'active' (its process is running) or 'stale' (left by a run that has ended)."""
    try:
        owner = int(LOCK.read_text().strip())
    except FileNotFoundError:
        return "none", None
    except (OSError, ValueError):
        return "active", None  # Unreadable: treat as active, never clear it.
    return ("stale" if owner_active(owner) is False else "active"), owner


def read_events(path):
    """Parse the run's output: JSON event lines plus any plain error lines."""
    events, errors = [], []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return events, errors
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict) and "event" in item:
                events.append(item)
        except ValueError:
            if re.match(r"^[A-Z_]+: ", line):
                errors.append(line)
    return events, errors


def record_id():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8-sig")).get("record_id")
    except (OSError, ValueError):
        return None


def data_range():
    """The record's data range in Reviewer, as seen by the most recent run that reached the check (IST)."""
    from datetime import timedelta, timezone
    name = record_id()
    ist = timezone(timedelta(hours=5, minutes=30))
    logs = sorted(RUNS.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True) if RUNS.is_dir() else []
    for path in logs[:20]:
        events, _ = read_events(path)
        for e in reversed(events):
            if e["event"] != "recordingRanges":
                continue
            for group in (e.get("data") or {}).get("groups", []):
                if group.get("name") == name:
                    try:  # Reviewer's group range fields are UTC without a zone marker.
                        start, end = (datetime.fromisoformat(group[k][:19]).replace(tzinfo=timezone.utc).astimezone(ist)
                                      for k in ("start", "end"))
                    except (KeyError, TypeError, ValueError):
                        return None
                    seen = local_time(e)
                    return dict(record=name, start=start.strftime("%Y-%m-%dT%H:%M"), end=end.strftime("%Y-%m-%dT%H:%M"),
                                checked=seen.strftime("%d/%m/%Y %H:%M") if seen else None)
    return None


def local_time(event):
    try:  # Event times are UTC; show this PC's local time.
        return datetime.fromisoformat(event["time"].replace("Z", "+00:00")).astimezone()
    except (KeyError, ValueError):
        return None


def describe(event):
    """A short readable line for the activity list, or None to hide the event."""
    name, data = event["event"], event.get("data") or {}
    when = local_time(event)
    at = when.strftime("%H:%M:%S") if when else ""
    if name == "start":
        return f"{at} Run started"
    if name == "fileVerified":
        return f"{at} Input file checked"
    if name == "applicationAccessible":
        return f"{at} Reviewer opened"
    if name == "profileStarted":
        return f"{at} Starting {PROFILE_NAMES.get(data.get('profile'), data.get('profile'))}"
    if name == "pdfVerified":
        output = Path(data.get("output", ""))
        return f"{at} {'Reused' if data.get('reused') else 'Saved'} {output.parent.name}\\{output.name}"
    if name == "reportRetry":
        return f"{at} Reviewer was slow; retrying {data.get('channel', 'the report')}"
    if name == "preflightWarning":
        return f"{at} Warning: {data.get('message', data.get('code', ''))}"
    if name == "messageLogSkipped":
        return f"{at} No messages in this time range; message PDFs skipped"
    if name == "failure":
        if "Stop requested" in (data.get("message") or ""):
            return f"{at} Stopped as requested; finished reports are kept"
        details = "; ".join(i.get("message", "") for i in data.get("details") or [] if isinstance(i, dict))
        return f"{at} FAILED: {details or data.get('message', '')}"
    if name == "complete":
        return f"{at} Finished"
    return None


def status():
    total, channels = expected_reports()
    lock, lock_owner = lock_state()
    with state_lock:
        run = load_run()
    result = dict(running=False, lock=lock, totalReports=total, channels=channels, offset=OFFSET, dataRange=data_range())
    if run is None:
        return result
    running = owner_active(run["pid"]) is not False
    events, errors = read_events(run["log"])
    done = [e for e in events if e["event"] == "pdfVerified"]
    folder = str(Path(done[0]["data"]["output"]).parent.parent) if done else None
    channel = None
    for e in reversed(events):
        if e["event"] == "channelsSelected":
            selected = (e.get("data") or {}).get("selected") or []
            channel = selected[0] if len(selected) == 1 else None
            break
    profile = next((e["data"].get("profile") for e in reversed(events) if e["event"] == "profileStarted"), None)
    failure = None
    for e in reversed(events):
        if e["event"] == "failure":
            data = e.get("data") or {}
            # Include the code and each issue: "Reporting preflight failed" alone does not say why.
            details = "; ".join(i.get("message", "") for i in data.get("details") or [] if isinstance(i, dict))
            failure = f"{data.get('code', 'ERROR')}: {data.get('message', '')}" + (f" ({details})" if details else "")
            break
    stop_requested = Path(run["stop"]).exists()
    if running:
        outcome = "Stopping" if stop_requested else "Running"
    elif any(e["event"] == "complete" for e in events):
        outcome = "Completed"
    elif stop_requested:
        outcome = "Stopped"
    else:
        outcome = "Failed"
    error = None
    if outcome == "Failed":
        error = failure or (errors[-1] if errors else "The run ended unexpectedly (the process was closed).")
    last = local_time(events[-1]) if events else None
    end_time = time.time() if running or last is None else last.timestamp()
    result.update(running=running, ownRunActive=running and lock_owner == run["pid"], outcome=outcome,
                  start=run["start"], end=run["end"], startedAt=run["startedAt"], showBrowser=run.get("showBrowser"),
                  elapsedSeconds=max(0, int(end_time - run["began"])), reportsDone=len(done),
                  messagesSkipped=any(e["event"] == "messageLogSkipped" for e in events), folder=folder,
                  currentProfile=PROFILE_NAMES.get(profile), currentChannel=channel, error=error,
                  activity=[line for line in (describe(e) for e in events) if line][-12:], logFile=run["log"])
    return result


def parse_local(value, label):
    if not isinstance(value, str) or not STAMP.match(value):
        raise ValueError(f"{label} must be a date and time")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def start_run(body):
    start, end = body.get("start"), body.get("end")
    if parse_local(start, "Start") >= parse_local(end, "End"):
        raise ValueError("End must be after start")
    show = body.get("showBrowser", True)
    if type(show) is not bool:
        raise ValueError("showBrowser must be true or false")
    with state_lock:
        run = load_run()
        if run and owner_active(run["pid"]) is not False:
            raise ValueError("A run is already in progress")
        lock, _ = lock_state()
        if lock == "active":
            raise ValueError("Another automation run is active. Wait for it to finish.")
        if lock == "stale":
            raise ValueError("A previous run was interrupted and left a lock. Press 'Clear lock' first.")
        if not PYTHON.is_file():
            raise ValueError(f"Python not found: {PYTHON}")
        if not CONFIG.is_file():
            raise ValueError(f"Configuration not found: {CONFIG}")
        RUNS.mkdir(exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S")
        log, stop = RUNS / f"{name}.log", RUNS / f"{name}.stop"
        # These values override .env for this run only; .env itself is not changed.
        env = dict(os.environ, REVIEWER_BLOCK_IMPORTS="true", HEADLESS="false" if show else "true",
                   WORKFLOW_CONFIG=str(CONFIG), REPORT_MODE="env",
                   START_DATETIME=f"{start}:00{OFFSET}", END_DATETIME=f"{end}:00{OFFSET}",
                   BATCH_STOP_FILE=str(stop), PYTHONUNBUFFERED="1")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with log.open("wb") as stream:
            process = subprocess.Popen([str(PYTHON), "-m", "reviewer", "workflow:run"], cwd=PROJECT, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       creationflags=flags, close_fds=True)
        save_run(dict(pid=process.pid, log=str(log), stop=str(stop), start=start, end=end, began=time.time(),
                      startedAt=datetime.now().strftime("%d/%m/%Y %H:%M:%S"), showBrowser=show))


def stop_run():
    with state_lock:
        run = load_run()
        if not run or owner_active(run["pid"]) is False:
            raise ValueError("No run is in progress")
        # The automation checks this file between reports, so the current report finishes first.
        Path(run["stop"]).write_text("stop", encoding="utf-8")


def clear_lock():
    """Use the project's recovery command; it removes a lock only when its owner has ended."""
    if lock_state()[0] != "stale":
        raise ValueError("There is no interrupted-run lock to clear")
    done = subprocess.run([str(PYTHON), "-m", "reviewer", "batch:recover"], cwd=PROJECT, capture_output=True,
                          text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or LOCK.exists():
        raise ValueError("The lock could not be cleared: " + (done.stderr or done.stdout).strip()[-300:])


def open_folder():
    folder = status().get("folder")
    if not folder or not Path(folder).is_dir():
        raise ValueError("No output folder yet")
    os.startfile(folder)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed(self):
        # Refuse other websites and DNS rebinding: only this page on this PC may use the server.
        if self.headers.get("Host") not in (f"{HOST}:{PORT}", f"localhost:{PORT}"):
            return False
        origin = self.headers.get("Origin")
        return origin in (None, f"http://{HOST}:{PORT}", f"http://localhost:{PORT}")

    def send(self, code, payload, kind="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed():
            return self.send(403, dict(error="Forbidden"))
        if self.path == "/api/status":
            return self.send(200, status())
        if self.path in FILES:
            name, kind = FILES[self.path]
            return self.send(200, (HERE / name).read_bytes(), kind)
        self.send(404, dict(error="Not found"))

    def do_POST(self):
        if not self.allowed() or self.headers.get("Content-Type") != "application/json":
            return self.send(403, dict(error="Forbidden"))
        actions = {"/api/run": start_run, "/api/stop": lambda body: stop_run(),
                   "/api/clear-lock": lambda body: clear_lock(), "/api/open-folder": lambda body: open_folder()}
        if self.path not in actions:
            return self.send(404, dict(error="Not found"))
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 10000)
            actions[self.path](json.loads(self.rfile.read(length) or b"{}"))
            self.send(200, status())
        except (ValueError, subprocess.TimeoutExpired) as error:
            self.send(400, dict(error=str(error)))


if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Report Runner is already running. Open http://{HOST}:{PORT} in your browser.", flush=True)
        sys.exit(0)
    print(f"Report Runner: open http://{HOST}:{PORT} in your browser.", flush=True)
    print("Closing this window does not stop a run in progress; use Stop on the page.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
