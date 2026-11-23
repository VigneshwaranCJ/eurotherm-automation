# Folder-based UHH reporting workflow

Updated 6 November 2026. This document supersedes earlier upload-first UI instructions.

The UI has no file upload step. Automation reads a .UHH from D:\Ceiyone\Input_uhh_files, imports it through Eurotherm Reviewer, navigates to Custom (next to Groups), matches an exact person/record ID such as SLS709, validates its 25 approved channels, then previews and exports the selected report scenario.

## Configuration

Copy workflow.example.json to workflow.json without overwriting an existing configuration. WORKFLOW_CONFIG can point to a different configuration within the workspace.

- input_dir defaults to D:\Ceiyone\Input_uhh_files.
- output_dir defaults to D:\Ceiyone\Output_report_files.
- input_file is optional only when exactly one .UHH exists in the input folder. Multiple files require explicit selection; the tool does not guess the newest file.
- record_id is the exact ID, for example SLS709.
- record_field must match the verified Custom response field: groupName or instrument.instrumentName. If the person ID appears in a separate person/batch field, commission an additional verified adapter. A person ID is not assumed to be an instrument ID.
- channels requires exactly 25 unique approved native names, written as `{ "name": "..." }`. The Custom record may contain more channels; those are switched off. Names must match Reviewer exactly: the live records use ULTF-01 to ULTF-06, not ULFT. An older `selector` value is accepted and ignored.
- graph_channels, if present in an older configuration, must now contain all approved names. All three scenarios use all approved channels.
- split_by_channel (default false). When true, channels may hold 1 to 100 approved names, such as all 35 channels of SLS733(EUT-01), and each channel gets its own PDF for each report type. Only that channel is shown in Reviewer for its report. Files are named by list position and channel, for example channel\01_ULTF-01.pdf, pen\01_ULTF-01.pdf and message\01_ULTF-01.pdf. Each PDF is checkpointed separately, so an interrupted run resumes at the next missing report. Each report takes about a minute, so 35 channels take roughly 1.5 to 2 hours per date range.
- With split_by_channel, Reviewer still cannot limit messages to one channel. Each Message Logs PDF therefore shows the whole record's messages, and is the same for every channel. The per-channel SUPPLEMENTARY CSV beside it lists only the alarms proven to belong to that channel. A window with no messages gives one SKIPPED_NO_MESSAGES entry for the run and no message PDFs. Batch runs write to Reports\<source>\channel, pen and message.

Each channel is set one at a time with Reviewer's Show/Hide Channel control and verified against Reviewer's own channel state, then the complete selection is verified again. Records are opened by Reviewer's group ID, so overlapping names such as EUT-01 and SLS733(EUT-01) cannot be confused.

The existing .env retains report dates, timezone mode, browser, certificate, paper and scaling settings. Choose a recording interval actually present in the input.

## Scenarios

| Scenario | Selection | Charts | Values | Messages | Separate messages | Cursor statistics |
| --- | --- | --- | --- | --- | --- | --- |
| Channels Logs | Individually set and verify all 25 channels | On | Off | Off | Off | On |
| Pen Logs | All 25 channels | On | On | On | On | On |
| Message Logs | All 25 channels | Off | Off | On | On | On |

Each scenario performs Custom selection, settings verification, native preview and PDF download. All current Include controls except Charts and Values remain enabled for Message Logs. The native chart adapter is the verified linear chart mechanism; any separate vendor pen visualization requires commissioning with real native examples.

### Report validation

Every Preview and PDF is checked before publication; a rejected download stays as a .part file.

| Check | Channels Logs | Pen Logs | Message Logs |
| --- | --- | --- | --- |
| Title and exact group on every page | Yes | Yes | Yes |
| Exact instrument | Real name | Real name | Real name, or Virtual Instrument for a Custom record |
| Selected channels present | Yes | Yes | Not applicable |
| Deselected channels | Must be absent | No data columns | Reported if named by messages |
| Cursor statistics | Required | Required | Not required (Reviewer omits them without a chart) |
| Messages section | Not applicable | Not applicable | Required |
| Requested start and end in the report | Yes | Yes | Yes |
| Every timestamp inside the range | Yes | Yes | Yes |
| Page count | Footers 1/N to N/N, equal to the page count and the Preview total, and at least the chart plus cursor pages | Same | Footers and Preview total |

Page counts come from the report's own footers. Reviewer's pageCheck value is logged and still applied as its native limit, but it does not count the whole report: it returned 1 for a 199-page PDF.

### Message scope limitation

Message Logs and Pen Logs can name deselected channels. This is native Reviewer behavior, not a selection failure. Tested on Reviewer's live installation (6 November 2026):

- Print requests send selectedChannels, but removing channels did not remove their messages.
- The only native message filter is by type (alarms, annotations, other), and a single alarm line can list many channels.
- Custom records with 33 and 35 channels produced identical message text, so a dedicated 25-channel record is not expected to help. Reviewer scopes messages to the source group.

The native PDF is never altered. Each export records deselectedChannelsInMessages in its pdfVerified event and logs messageScopeWarning when any are found.

### Supplementary filtered message list

Each Message Logs export also writes `SUPPLEMENTARY_filtered_messages_<native report>.csv` beside the PDF. It is derived data, not a Reviewer report. Its filename, header and every data row say so, and its header records the native PDF's name and SHA-256.

An entry is included only when it is an alarm-type message in Reviewer's exact format and a selected channel's number and name both match the record. Deselected channels on the same line are removed and counted in otherChannelsRemoved.

| Message | Result | Counted as |
| --- | --- | --- |
| Alarm naming a selected channel with the correct number and name | Included, one row per selected channel | included |
| Alarm naming only deselected channels | Excluded | excludedDeselectedOnly |
| Selected name with the wrong number, unreadable alarm format, or no channel data | Excluded, including the whole line | excludedUnreliable |
| Login, email, acknowledgement, annotation and other non-alarm messages | Excluded, since no channel is identified | excludedNoChannel |

The list is withheld (supplementaryMessagesWithheld) when the message count from Reviewer's data does not match the validated PDF. The native PDF is still published. Excluded messages remain visible in the native PDF, which stays the complete record.

### Days without messages

Before any Message Logs preview, the workflow asks Reviewer for the interval's messages. When Reviewer confirms there are none:

- The scenario is marked SKIPPED_NO_MESSAGES, and no PDF or list is created.
- A messageLogSkipped event records the date, instrument, record, interval and reason in the run log, and in the day's execution.log during batch runs.
- The remaining reports and batch days continue, and the run exits successfully.
- A batch day completes with its two chart reports and the recorded skip.

A blank preview when Reviewer does list messages remains a failure. The UI shows SKIPPED_NO_MESSAGES for a Message Logs run. A run of all three reports shows Success, with the skip in its message.

### Import date check

Exports and `full` check the requested dates against the input file before importing, and stop with INTERVAL_OUTSIDE_INPUT when they do not overlap. `yesterday` mode stops with INTERVAL_UNVERIFIED if Reviewer has no matching group to supply the timezone. `latestAvailable` is derived from the recording, and import-only commands request no dates.

### Inputs after organizing

Batch organizing keeps originals and adds dated copies. Single-file selection now compares content: identical copies count as one file and the shallowest path is used. Different content with the same name, or several different files without input_file, still stops instead of guessing.

## Run from the UI

Start python -m reviewer.history_api in an activated Python terminal and npm run dev in the UI terminal. The action list provides:

- Import UHH into Reviewer: import/validate the selected folder input without requiring channel mapping.
- Channels Logs, Pen Logs, Message Logs: import when needed, then export only that scenario.
- Export graph, pen & message logs: execute all three in order.
- Validate 25-channel workflow: preview all three using an already imported source, without importing or exporting.

A deliberate Run click for an import/export workflow authorizes the exact selected source hash for one guarded execution. The runner computes the stable hash and passes it to the existing importer, with DRY_RUN=false confined to that child process. It does not change .env. Exact archived duplicates skip submission. Uncertain or pending import attempts still stop for reconciliation. A rerun of an import record refuses a changed input hash.

The legacy single-report actions retain their configured .env inputs. Use the workflow scenarios for this folder-based process.

## Run from the CLI

Activate the existing Python environment, then:

```powershell
python -m reviewer workflow:plan
python -m reviewer workflow:preview
python -m reviewer workflow:channels
python -m reviewer workflow:pen
python -m reviewer workflow:messages
python -m reviewer workflow:run
```

CLI imports retain the original DRY_RUN and explicit --authorize-import=<verified SHA-256> safeguards. Preview never imports missing data. Export commands download after validation even with DRY_RUN=true when the source is already imported.

## Modules

- pipeline/inputs.py: select the folder input independently of channel configuration.
- pipeline/configuration.py: validate record/channel configuration and expose setup readiness.
- pipeline/selection.py: exact unique ID matching, channel mapping/sample checks and individually verified checkbox states.
- pipeline/profiles.py: the three Include-option profiles and organized output folders.
- pipeline/runner.py: verified import, Custom selection, preflight, previews and exports.
- pipeline/journal.py: atomic, content-bound export checkpoints.
- instrument/: stable source hash, vendor metadata, archive comparison and guarded native import.
- reports/: native settings, preview checks, staged downloads and parsed PDF validation.
- ui_runs.py/history_api.py: job lifecycle, process isolation, statuses, details, logs and output links.
- UI components/hooks/services/utils: workflow controls, rendering, polling, API access and formatting.

## Outputs and recovery

Exports are organized under Output_report_files/<record ID>/<run ID>/ with channel, pen and message subfolders, sanitized names and timestamped PDFs. `workflow:run` creates all three in one run folder. Reports for the same input, record, channels, dates and options always share that folder, whichever command made them, including after an interrupted run. All outputs are linked in Run details. A rerun with the same values reuses the verified reports and creates nothing new; change the dates, or remove the matching file from logs/export-journal, to generate them again. Reports created before this layout stay where they are and are not reused, so the first run makes a new complete set. Batch runs keep their dated Reports folders.

Downloads remain .part files until PDF validation succeeds. Export checkpoints bind the input SHA, record and channel mapping, interval, report settings and pipeline version. A rerun reuses only unchanged verified files; missing or changed files are regenerated. This profile update uses checkpoint version 2 so prior Include settings are not reused.

Do not remove import-attempt journals to force a retry. Reconcile pending native imports against Reviewer evidence first. Interrupted locks require verifying the owning process. API restart recovery uses final console events where available; otherwise the run is Unknown. No automatic import resubmission occurs.

## Verification and acceptance status

The actual folder input Group-1~20260830_820FF93000000412.uhh is readable by the vendor metadata helper. It records SLS-GL-EUT-01 / Group 1, 35 source points, from 30 Aug 2026 03:38 UTC to 31 Aug 2026 15:56:58.125 UTC. These source points are not an approved selection of 25 Custom channels. The final Custom record and 25-channel list are pending confirmation. No real import has been executed by this workflow.

Automated tests cover exact/missing/ambiguous records, missing/extra/duplicate/sampleless channels, profile settings, scenario isolation, invalid inputs, duplicate controls, export reuse, interrupted state, API rules, and regression behavior. Browser tests verify no file-input control is rendered.

Before production acceptance, an operator must approve the identity/channel mapping, verify native Custom requests and selectors, execute one authorized import, compare all three previews and PDFs with manual native exports, test duplicate and interrupted imports, verify rerun recovery, record defects and obtain user sign-off. Unit/browser fixtures are not live acceptance evidence.

## Deployment and handover

For local compiled deployment, build the UI with npm run build, stop the existing API on port 8765, then run python -m reviewer.web from the activated Python project. Open http://127.0.0.1:8765. This serves the compiled UI and API together on localhost. Production/service rollout remains pending acceptance; no Windows task or service is registered automatically.

Validation commands:

```powershell
python -m unittest discover -s tests -q
python tools/test_ui_browser.py
```

In the UI project run npm run build, npm run lint and node --test tests/automation.test.js.
