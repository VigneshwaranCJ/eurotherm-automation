# Eurotherm Reviewer Automation — Python Playwright

Python implementation of the workflows in `D:\Ceiyone\EurothermReviewerAutomation`.
Both projects read the same UHH file and existing Reviewer archive, select the
same instrument/group and interval, configure native print settings, validate
Preview and download/verify native PDFs. Python runs Playwright directly; it does
not delegate automation to Node or TypeScript.

## Setup

Requires Windows, standalone Python 3.12 (3.11 is the minimum), the .NET 10 runtime,
Google Chrome and installed Eurotherm Reviewer. Node.js 22 is only needed to rebuild the UI.

### 1. Install the runtimes

```powershell
winget install --id Python.Python.3.12 --scope user
winget install Microsoft.DotNet.Runtime.10
```

Open a new terminal, then confirm:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version   # Python 3.12.x
dotnet --list-runtimes                                                 # Must list Microsoft.NETCore.App 10.x
```

**Python.** Use a standalone installation. Setup refuses interpreters in temporary or
tool-managed folders (`AppData\Local\Temp`, `.cache`, `codex-runtimes`), because a
virtual environment stops working when its base Python moves or updates. The empty
`python.exe` alias from the Microsoft Store is not Python and is ignored.

**.NET 10.** `tools\reader\VendorInspect.dll` targets `net10.0` and is started with
`dotnet` from `PATH`. Without it, `diagnostics`, `report:dry`, `report`, `import:test`,
`full`, every `workflow:*` command and every `batch:*` command stop with an error
naming the install command. `file:check`, `discover` and `datasources` do not need it.

### 2. Build the project environment

```powershell
Set-Location D:\Ceiyone\EurothermReviewerAutomationPython
.\Initialize.ps1 -Python "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
.\.venv\Scripts\python.exe -m reviewer check-env
.\.venv\Scripts\python.exe -m reviewer check-config
```

Setup rebuilds `.venv` when `-Python` is given, when its interpreter no longer works,
or when it is based on a temporary Python and a standalone one is available. It installs
`requirements.lock.txt`, preserves an existing `.env`, then runs `check-env`.

`check-env` validates Python, locked packages, .NET 10, the metadata helper, the vendor
library, Chrome and Reviewer's HTTPS port. It exits 1 if any check fails. The helper's
source is `tools\VendorInspect.cs`, and it uses the Eurotherm library read-only.
A virtual environment records its base Python's path, so rerun setup after moving the
project to another user or machine. Keep the project folder directly under the
workspace, because paths in `.env` must stay inside the folder above it.

### 3. Build the UI (only after UI changes)

```powershell
Set-Location D:\Ceiyone\eurothermReviewerAutomationUI
npm ci
npm run build
```

`REVIEWER_BLOCK_IMPORTS=true` in the process environment stops every import before any
file is selected, even with authorization. It is inherited by UI runs. Use it for all
testing. It is read from the environment only, not from `.env`. Runtime logs,
temporary files and screenshots stay in the Python project. The default input is
`D:\Ceiyone\uhh_files\Group-6~20260723_823E8130050002A0.uhh` and the PDF directory is
`D:\Ceiyone\downloads`.

## Matching commands

The implementation is organized into focused packages for application flow,
shared utilities, instrument handling, Reviewer UI, health checks and reporting.
See [Architecture](docs/Architecture.md) for the module map and compatibility details.

With the project's virtual environment activated, the short launcher is:

```powershell
Set-Location D:\Ceiyone\EurothermReviewerAutomationPython
python reviwer report
```

`reviwer` preserves the requested spelling and accepts all the same commands and
arguments as `python -m reviewer`. It uses the existing configuration and safeguards.

Run the TypeScript equivalents with `.\.runtime\npm.cmd run <command>` from the
reference folder; run Python with `.\.venv\Scripts\python.exe -m reviewer <command>`.

| Command | Behavior in both projects |
| --- | --- |
| `file:check` | Read/hash the configured UHH while excluding writers; verify stability |
| `discover` | Check Reviewer, inspect the import UI without selecting a file, save screenshot |
| `datasources` | Inspect instrument network/pull-service state and last transfer times |
| `diagnostics` | Verify metadata, group identity, archive hash, disk/indexing readiness, interval and notifications |
| `report:dry` | Verify native chart, print settings and Preview; no PDF download |
| `report` | Verify Preview, download native PDF and check identity, channels, values and exact boundaries |
| `import:test` | Skip an exact archive duplicate; otherwise require separate SHA authorization |
| `full` | Guarded import if needed, then Preview; download only when `DRY_RUN=false` |

An explicit `report` downloads even with `DRY_RUN=true`, matching the reference.
`DRY_RUN` protects file submission and controls downloads for `full`.

Example:

```powershell
.\.venv\Scripts\python.exe -m reviewer file:check
.\.venv\Scripts\python.exe -m reviewer diagnostics
.\.venv\Scripts\python.exe -m reviewer report:dry
.\.venv\Scripts\python.exe -m reviewer report
```

## Configuration and safeguards

`.env.example` lists the shared settings. `REPORT_MODE=env` requires timestamps
with seconds and explicit offsets, for example `2026-10-08T00:00:00+01:00`.
`yesterday` uses the instrument's timezone and rejects daylight-saving days that
are not 24 hours. `latestAvailable` explicitly selects the last 15 minutes of
recording, labels the report HISTORICAL TEST REPORT and uses HistoricalTest in
the filename. `file` confines the interval to the configured UHH recording.
Missing dates never fall back to another interval or group. Batch-specific
reporting remains unsupported in both implementations.

Only HTTPS localhost Reviewer URLs are allowed. Certificate errors fail by
default. An explicitly enabled localhost TLS exception restricts requests to
localhost. `BROWSER_CHANNEL=chrome` uses installed Chrome; an empty value selects
Playwright Chromium, which must be installed separately.

Import commands require `DRY_RUN=false` and `--authorize-import=<verified SHA-256>`.
An uncertain state, different archive content, changed input, multiple-file
request or previous import attempt prevents submission. No automatic import
retry occurs. Python also acquires the reference project's run lock and shares
its import-attempt journal when the reference folder exists. This prevents
overlapping operations and repeat submission across the two projects. An
interrupted-run lock requires checking its owning process before removal.

## Tests and comparison

`tests\test_scenarios.py` runs Channels Logs, Pen Logs and Message Logs through the
real pipeline in headless Chrome against `tests\reviewer_stub.py`, using real PDFs and
failure cases. `tests\test_release_gates.py` covers import date checks, single-file
selection, skips, filtered messages, environment checks and the real importer against a
local HTTP server. Neither contacts Reviewer, and both require Google Chrome.

`tools\test_ui_live.py` drives the compiled UI against the real API and CLI. It refuses
to start unless `REVIEWER_BLOCK_IMPORTS=true`.

```powershell
.\.venv\Scripts\python.exe tools\run_tests.py
.\.venv\Scripts\python.exe tools\compare_projects.py
.\.venv\Scripts\python.exe tools\verify_reference_pdf.py
```

The comparison runs both CLIs sequentially, saves individual transcripts and
`results.json` under a timestamped `logs\comparison-*` folder, and compares hashes,
group identity, intervals, preflight issue codes, print settings and PDF counts
when available. It passes no import authorization. Its `full` case uses an
already imported file with `DRY_RUN=true`. Its `report` case explicitly requests
a labelled historical native PDF. To resume interrupted checks, pass the prior
comparison folder as the script's argument. Cached blocked checks describe the
original machine state; use a new comparison after restoring disk space.

`passed=true` with `blocked=true` means the command refused safely; it does not
mean reporting completed. The offline PDF checker validates an existing native
21-page report against original run evidence; it does not generate a new report.
See [verification details](docs/Verification.md) for current results and limits.

## Daily reporting

`Run-DailyReport.cmd` runs reporting only, reads exact dates from `.env`, and logs
to `logs\scheduled-run.log`. It never authorizes imports. The optional
`Register-DailyReport.ps1` creates a separate **Eurotherm Daily PDF Report Python**
task at 10:00 AM IST with the same logged-in-user and overlap behavior as the
reference task. Setup does not register or modify scheduled tasks. Choose one
production launcher or separate their times; shared run locking prevents both
projects from driving Reviewer at once.

## Custom record and 25-channel pipeline

See [Workflow operations](docs/Workflow-Operations.md) for the modular pipeline, required channel/record mappings, graph/pen-log/message-log profiles, safe reruns, local compiled deployment and pending acceptance checklist. Copy workflow.example.json to workflow.json and complete it before using workflow:plan, workflow:preview or workflow:run. These commands use Input_uhh_files and Output_report_files independently of legacy report settings.
