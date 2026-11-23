# Verification

## November 6, 2026 (IST)

Automated: 153 Python tests passed, 5 UI tests passed, UI lint and build passed, and the UI browser test passed.

Live against Reviewer, with `REVIEWER_BLOCK_IMPORTS=true` and a stand-in selection of the first 25 of 35 channels on `SLS733(EUT-01)`. No import was submitted. Reviewer's archive file counts were unchanged afterwards.

| Check | Result |
| --- | --- |
| Dates outside the input, `workflow:run` and `full` | Stopped with INTERVAL_OUTSIDE_INPUT before import |
| Valid dates, or `import:test`, on a file not in Reviewer | Stopped with IMPORTS_BLOCKED; nothing submitted |
| `import:test`, file already archived | Skipped as an exact duplicate |
| Single-file `report` | Passed, 199 pages |
| Channels Logs | Passed, 2 pages |
| Pen Logs | Passed, 149 pages |
| Message Logs | Passed, 23 pages, plus the supplementary list |
| Window with no messages | SKIPPED_NO_MESSAGES, no PDF; other reports completed |
| `batch:organize`, then single-file run | Passed |
| Two-file batch, three recording days | Completed; rerun reused verified reports |
| Web UI, including downloads | Passed |

Not yet tested live: a real import, a batch containing a real import, a batch day with no messages (covered by automated tests and separate live runs), and `batch:run` started from the web UI. The final Custom record and channel list are pending.

The real importer and upload guard were tested only in real Chrome against a local HTTP server. Reviewer's live endpoint may behave differently.

The rest of this document records the October 14 comparison with the former reference project.

## October 14, 2026 (IST)

The Python project implements the same eight command workflows as the TypeScript
reference. No differences were found in the 67 evidence comparisons available
under the current live environment. Successful new native Preview/PDF generation
is still unverified because Reviewer currently disables indexing due to low disk
space. This is not a claim of complete end-to-end reporting validation.

## Automated checks

| Check | Result |
| --- | --- |
| TypeScript `npm test` | 20 passed, 0 failed |
| TypeScript `npm run typecheck` | Passed |
| Python `python -m unittest discover -s tests -v` | 37 passed, 0 failed |
| Python compilation | Passed for `reviewer`, `tests`, and `tools` |
| Python dependency integrity (`pip check`) | Passed |
| Python setup and task-registration PowerShell syntax | Passed |
| Offline Python PDF verification | Existing native PDF: 21 pages, all 30 channels, title/instrument/group, values and exact boundaries verified |

Python tests cover command policy, exact-offset dates, missing-data behavior,
daylight-saving day length, historical bounds, workspace paths, group identity,
archive hash collisions, run locking, browser cleanup, readiness failures,
print checkbox rejection, report text and boundaries, and workflow sequencing.
Mocked import transport tests check single-file requests, persistent attempt
journals, blocked multiple-file requests, incomplete native results and no
automatic resubmission. No test transport contacts the live import endpoint.

## Live comparison

Both projects were run sequentially in headed Chrome against `https://localhost`.
Historical-mode overrides were process-local; both `.env` files remain in exact
environment-date mode. All eight CLI commands were exercised, with diagnostics
tested in two range modes, giving 18 command runs.

| Command / range mode | TypeScript | Python |
| --- | --- | --- |
| `file:check` / env | Passed | Passed |
| `discover` / env | Passed; no file selected | Passed; no file selected |
| `datasources` / env | Passed | Passed |
| `diagnostics` / env | Safely blocked | Safely blocked |
| `import:test` / env | Exact archive duplicate skipped | Exact archive duplicate skipped |
| `diagnostics` / latestAvailable | Safely blocked | Safely blocked |
| `report:dry` / latestAvailable | Safely blocked before chart/Preview | Safely blocked before chart/Preview |
| `full` / latestAvailable, DRY_RUN=true | Duplicate skipped; reporting safely blocked | Duplicate skipped; reporting safely blocked |
| `report` / latestAvailable | Safely blocked; no PDF downloaded | Safely blocked; no PDF downloaded |

Eight runs completed successfully; ten demonstrated safe refusal. All 67
comparisons matched: command/range/title settings, file hash and size, import UI,
data-source instruments, vendor metadata, group count and identity, archive
evidence, duplicate skip, exact selected report intervals and preflight codes.
There were zero final command-comparison or evidence-comparison failures.

Input: `D:\Ceiyone\uhh_files\Group-6~20260723_823E8130050002A0.uhh`, 400349 bytes.
SHA-256: `e5d03b1b614a326952d441055b360ccbc3c240195815b4c8177543f1da744678`.
Both projects matched **Group 6 / SLS-GL-EUT-02 / 000A8D823E81** and verified the
same exact archived content. No new UHH upload was performed.

Evidence:

- [Comparison summary](../logs/comparison-20261014T090931Z/summary.json)
- [Full comparison results and transcript paths](../logs/comparison-20261014T090931Z/results.json)
- [Offline preserved-PDF validation](../logs/offline-pdf-validation.json)

Initial interrupted attempts and a transient Chrome resource failure are retained
in earlier run logs. The final comparison retried the failed diagnostic and
reused completed checks. A Python host-check startup failure was corrected by
using lightweight Windows disk/service queries in place of another PowerShell
process while Chrome runs.

## Current live blockers and remaining checks

Reviewer reports approximately 2 GB free on C:, below its configured 5 GB minimum,
`indexingEnable=false`, and disk/Elastic status `ErrorDiskFull`. Both projects
return `LOW_DISK_SPACE` and `INDEXING_DISABLED`; no threshold was lowered.

The configured interval is October 8–9, 2026, at offset +01:00. The selected
Group 6 recording ends August 1, 2026. Both projects additionally report
`MISSING_DATA` for the configured interval; another group or date is never
substituted automatically. Stale source transfer times are logged separately.

After disk space is restored and Reviewer enables indexing, run a new comparison
without a resume argument:

```powershell
Set-Location D:\Ceiyone\EurothermReviewerAutomationPython
.\.venv\Scripts\python.exe tools\compare_projects.py
```

This explicitly tests labelled historical Preview and new native PDF generation.
It does not make the missing October Group 6 interval available. Successful new
imports were not live-tested because the selected file is already imported and
no separate import SHA authorization was given. Batch-specific reporting remains
unsupported in both projects. No second scheduled task was registered, and the
existing daily task was not changed.
