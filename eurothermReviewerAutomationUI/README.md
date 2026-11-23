# Eurotherm history UI

This React UI reads real run logs and output files through a local Python API with Run and Rerun controls.

Start the API in one PowerShell terminal:

```powershell
cd D:\Ceiyone\EurothermReviewerAutomationPython
.\.venv\Scripts\python.exe -m reviewer.history_api
```

Start the UI in another terminal:

```powershell
cd D:\Ceiyone\eurothermReviewerAutomationUI
npm run dev
```

Open the URL printed by Vite. Keep both terminals running. The UI refreshes every 2 seconds and groups records by IST date. Vite proxies /api to localhost port 8765; preview uses the same proxy. A separately deployed production build needs an equivalent API proxy.

The API uses the Python project's configured LOG_DIR, REPORT_OUTPUT_DIR, and DOWNLOAD_DIR. It exposes known output files and run logs only. Use Run automation to launch report, report preview, diagnostics, data sources, discovery, or input checking. Rerun creates a new execution using the current .env configuration. Only one UI execution runs at a time; the existing automation lock also prevents overlap with CLI runs. UI execution metadata and console logs persist under LOG_DIR/ui-runs. Keep the API running during execution. After an API restart, an unconfirmed execution shows Unknown; check its logs before rerunning.

Failed runs show Failed. Verified PDFs and completed runs show Success. Older runs without a completion event show Unknown. Existing files without matching run evidence show Available. Unsupported download actions are not fabricated.


## UI modules and verification

`src/App.jsx` composes the page. `src/components/` contains RunControls, HistoryTable, RunDetails, and StatusBadge. `src/hooks/useAutomation.js` owns polling and execution state; `src/services/automation.js` handles API requests; `src/utils/history.js` groups dates and labels commands.

Run build and lint in the UI folder:

```powershell
npm run build
npm run lint
```

Run verification from the Python project:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/test_ui_browser.py
.\.venv\Scripts\python.exe tools/test_ui_automation.py
```

The browser check uses deterministic API responses to test controls, polling, details, status changes, and mobile layout. It requires the UI build and installed Chrome. The live automation check performs input checking, reruns it, then validates the report preview. It downloads a PDF only if preview validation succeeds. It uses HEADLESS=true for that test process and leaves .env unchanged. Results are saved to the Python logs/ui-automation-smoke.json file.

On 14 Oct 2026, real API Run and Rerun input checks passed. Report preview failed with a 90-second timeout on Reviewer's Data Sources page after browser resource errors. A new PDF download was not verified. Browser checks and 44 Python tests passed.

