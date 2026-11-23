# Modular Python architecture

The Custom-record 25-channel pipeline is isolated under `reviewer/pipeline/`.
See [workflow operations and acceptance](Workflow-Operations.md) for its modules,
configuration contract, profiles, checkpoint recovery and deployment entry point.

The CLI coordinates focused domain modules. Browser operations, file validation,
readiness decisions and report content checks can be maintained independently.

```text
reviewer/
  __main__.py               python -m reviewer entry point
  config.py                 Settings and workspace paths
  ranges.py                 Exact, yesterday, historical and file intervals
  application/
    cli.py                  Argument parsing and dispatch
    commands.py             Command policy
    run.py                  Locks, logging, browser lifecycle and failures
    workflow.py             Workflow orchestration
  common/
    errors.py               Structured workflow errors
    time.py                 UTC parsing and formatting
    locking.py              Exclusive run locks
    logging.py              JSON execution evidence
    process.py              Windows subprocess helper
  instrument/
    validation.py           Stable UHH validation and hashing
    metadata.py             Read-only vendor metadata adapter
    identity.py             Unique instrument/group mapping
    duplicates.py           Archive and exact-content checks
    importer.py             SHA authorization, request guard and attempt journal
  ui/
    browser.py              Playwright lifecycle and localhost TLS handling
    groups.py               Native group filters and cards
    batches.py              Read-only batch inspection
    chart.py                Chart controls and accepted-date verification
    status.py               Native database/indexing status
    sources.py              Instrument network and transfer status
    notifications.py        Read-only notifications
  health/
    environment.py          Machine prerequisites (check-env)
    host.py                 Windows disks and services
    readiness.py            Pure readiness decisions
    preflight.py            Reporting preflight and interval diagnostics
  reports/
    settings.py             Native print controls
    validation.py           Identity, channels, dates, values and page counts
    preview.py              Native page gate and Preview checks
    pdf.py                  Native download and parsed PDF verification
    messages.py             Message query and supplementary filtered list
  pipeline/
    configuration.py        Workflow configuration and setup status
    inputs.py               Workflow folders and content-based input selection
    selection.py            Exact record match and Show/Hide Channel selection
    profiles.py             Channels, Pen and Message report settings
    runner.py               Three-scenario orchestration, skips and exports
    journal.py              Verified export checkpoints
    calendar.py             Recording-day discovery and organization
    batch.py                Sequential day queue
    state.py                SQLite claims and completion evidence
    recovery.py             Conservative stale-claim recovery
  history_api.py, ui_runs.py, web.py   Local API, job control and compiled UI
```

## Scenario flow

```text
Validate input and read metadata
  -> Already in Reviewer's archive?
       No:  preview stops; otherwise check dates against the input, then guarded import
       Yes: continue
  -> Check group and archive hash -> inspect sources -> find exact Custom record
  -> Preflight: disk, indexing and interval
  -> For each scenario (Channels, Pen, Message):
       Reuse a verified checkpoint, or:
       Open the record by group ID and verify the chart opened it
       Set each channel with Show/Hide Channel and verify it
       Message Logs: ask Reviewer for messages; none means SKIPPED_NO_MESSAGES, continue
       Configure print -> validate Preview -> download -> validate PDF
       Message Logs: write the SUPPLEMENTARY list beside the untouched native PDF
```

Imports require every one of these: no process block, `DRY_RUN=false`, an authorization matching the file's hash, a certain import state, no previous attempt, and matching dates when a report is requested.

## Dependencies and compatibility

`application` composes domain operations. `common` has no dependency on browser
or application modules. Instrument identity and duplicate checks do not depend
on Playwright. Readiness and report validation are pure decisions shared by their
callers. The importer checks native status and readiness before submission.
Browser-evaluated JavaScript stays with its relevant UI operation.

`config.py` and `ranges.py` remain focused modules. The top-level `core.py`,
`uhh.py`, `diagnostics.py`, `reporting.py`, `workflow.py`, `browser.py`, `groups.py`
and `chart.py` now contain compatibility exports. Existing tools retain their
imports; implementation modules import focused modules directly. Tests patch
dependencies at their implementation locations and check compatibility exports.

Both entry points call `application.cli.main`:

```powershell
python reviwer report
python -m reviewer report
```

Commands, settings, output paths, shared lock, import journal and daily launcher
retain their behavior. Playwright, pypdf and the read-only vendor helper retain
their existing roles.

## Refactor verification — October 14, 2026

All 38 tests passed: 37 existing regression tests and compatibility verification.
Compilation, configuration, CLI help, stable UHH file validation through the
short launcher, and offline verification of the preserved 21-page/30-channel
native PDF passed. The input SHA-256 remains
`e5d03b1b614a326952d441055b360ccbc3c240195815b4c8177543f1da744678`.

Native reporting was not rerun for this refactor. Previously observed low disk
space and disabled indexing remain the last known live blockers; see
[verification details](Verification.md). No imports or task registration occurred.
