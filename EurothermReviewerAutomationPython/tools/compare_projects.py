"""Run both CLIs sequentially against the same file and compare their evidence.

No import authorization is passed. import:test must prove it skipped an archive
duplicate. Historical PDF generation is explicit and does not rewrite either .env.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT.parent / "EurothermReviewerAutomation"


def events(output):
    result = []
    for line in output.splitlines():
        try:
            record = json.loads(line)
            if isinstance(record, dict) and "event" in record:
                result.append(record)
        except ValueError:
            pass
    return result


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "logs" / f"comparison-{stamp}"
    if not folder.is_relative_to(ROOT / "logs"):
        raise ValueError("Comparison results must stay under this project's logs folder")
    folder.mkdir(parents=True, exist_ok=True)
    cases = [
        ("file:check", "env"), ("discover", "env"), ("datasources", "env"),
        ("diagnostics", "env"), ("import:test", "env"),
        ("diagnostics", "latestAvailable"), ("report:dry", "latestAvailable"),
        ("full", "latestAvailable"), ("report", "latestAvailable"),
    ]
    results = []
    for command, mode in cases:
        pair = []
        for name, cwd, cli in [
            ("typescript", REFERENCE, [str(REFERENCE / ".runtime" / "node.exe"), "dist/index.js"]),
            ("python", ROOT, [sys.executable, "-m", "reviewer"]),
        ]:
            env = dict(os.environ, REPORT_MODE=mode, DRY_RUN="true")
            print(f"Running {name}: {command} ({mode})", flush=True)
            filename = folder / f"{name}-{command.replace(':', '-')}-{mode}.txt"
            status_file = filename.with_suffix(".status.json")
            cached = filename.exists() and status_file.exists()
            if cached:
                output = filename.read_text(encoding="utf-8")
                exit_code = json.loads(status_file.read_text(encoding="utf-8"))["exitCode"]
                failed = next((r["data"] for r in events(output) if r["event"] == "failure"), None)
                if exit_code != 0 and (failed or {}).get("code") not in {"LOW_DISK_SPACE", "INDEXING_DISABLED", "MISSING_DATA"}:
                    cached = False
            if not cached:
                completed = subprocess.run(cli + [command], cwd=cwd, env=env,
                                           capture_output=True, encoding="utf-8", errors="replace", timeout=600)
                output, exit_code = completed.stdout + completed.stderr, completed.returncode
                filename.write_text(output, encoding="utf-8")
                status_file.write_text(json.dumps(dict(exitCode=exit_code)), encoding="utf-8")
            records = events(output)
            failure = next((r["data"] for r in records if r["event"] == "failure"), None)
            issue_codes = [issue["code"] for issue in ((failure or {}).get("details") or [])]
            blocked = bool(failure and failure["code"] in {"LOW_DISK_SPACE", "INDEXING_DISABLED"}
                           and command in {"diagnostics", "report:dry", "full", "report"})
            expected = (command == "diagnostics" and mode == "env")
            passed = (exit_code != 0 and failure and "MISSING_DATA" in issue_codes) if expected else exit_code == 0
            if blocked:
                passed = exit_code != 0 and not any(r["event"] in {"pdfVerified", "importSelected", "importNativeComplete"} for r in records)
            if command == "import:test":
                passed = passed and any(r["event"] == "importSkipped" for r in records)
            if command in {"report:dry", "full"} and not blocked:
                passed = passed and any(r["event"] == "dryRunComplete" for r in records) and not any(r["event"] == "pdfVerified" for r in records)
            pdf = next((r["data"] for r in records if r["event"] == "pdfVerified"), None)
            if command == "report" and not blocked:
                passed = passed and pdf is not None
            summary = dict(project=name, command=command, mode=mode, exitCode=exit_code,
                           passed=bool(passed), blocked=blocked, issueCodes=issue_codes, failure=failure, pdf=pdf, evidence=str(filename))
            results.append(summary)
            pair.append(records)
            (folder / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            label = 'BLOCKED (safe refusal)' if passed and blocked else 'PASS' if passed else 'FAIL'
            print(f"  {label} (exit {exit_code}); {filename.name}", flush=True)
        # Compare concrete identity and interval evidence rather than success codes alone.
        for event, keys in [("start", ("command", "dryRun", "reportMode", "reportTitle")),
                            ("fileVerified", ("sha256", "size")),
                            ("importInterface", None), ("dataSources", ("instruments",)), ("uhhMetadata", None),
                            ("groups", None), ("importEvidence", ("status", "groupId", "archive")),
                            ("groupMatched", ("id", "name", "instrument", "start", "end")),
                            ("duplicateCheck", None), ("importSkipped", None),
                            ("reportInterval", ("start", "end", "mode", "historical")),
                            ("chart", ("start", "end", "channels")), ("preview", ("pages", "graphics", "tables")),
                            ("printSettings", None), ("pdfVerified", ("pages", "channelCount", "readable"))]:
            data = [next((r["data"] for r in records if r["event"] == event), None) for records in pair]
            if any(item is not None for item in data):
                comparable = [({k: item.get(k) for k in keys} if keys else item) if item else None for item in data]
                results.append(dict(command=command, mode=mode, comparison=event, passed=comparable[0] == comparable[1], values=comparable))
        issue_sets = [[issue["code"] for r in records if r["event"] == "preflight" for issue in r["data"]["issues"]] for records in pair]
        if any(issue_sets):
            results.append(dict(command=command, mode=mode, comparison="preflightIssues", passed=issue_sets[0] == issue_sets[1], values=issue_sets))
        (folder / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Results: {folder / 'results.json'}", flush=True)
    command_results = [r for r in results if "project" in r]
    summary = dict(
        commandChecks=len(command_results),
        checksCompletedSuccessfully=sum(r["passed"] and not r["blocked"] for r in command_results),
        safelyBlocked=sum(r["passed"] and r["blocked"] for r in command_results),
        failed=sum(not r["passed"] for r in results),
        comparisonChecks=sum("comparison" in r for r in results),
        freshNativePdfVerified=all(any(r["project"] == project and r["command"] == "report" and r["pdf"] for r in command_results)
                                   for project in ("typescript", "python")),
    )
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
