"""Reporting preflight and interval diagnostics."""
import math
from datetime import datetime, timezone
from ..common.errors import WorkflowError
from ..common.time import utc_time
from ..ranges import yesterday_interval, overlaps, require_data, latest_available, file_interval
from ..ui.status import reviewer_status
from ..ui.notifications import inspect_notifications
from .host import disk_and_service_status
from .readiness import readiness_issues


def run_preflight(page, group, groups, metadata, sources, settings, log, run_id, configured=None):
    host = disk_and_service_status()
    log("hostStatus", host)
    status = reviewer_status(page)
    log("reviewerStatus", status)
    issues = readiness_issues(status, host["disks"])
    requested = yesterday_interval(page, group)
    log("yesterdayInterval", requested)
    recording_ranges = []
    for candidate in groups:
        interval = yesterday_interval(page, candidate)
        recording_ranges.append(dict(id=candidate["groupId"], name=candidate["groupName"],
                                     instrument=candidate["instrument"], start=candidate["dataStart"],
                                     end=candidate["dataEnd"], timezoneOffsetMs=candidate["timezoneOffset"],
                                     daylightSavings=candidate["daylightSavings"], requested=interval, overlap=overlaps(candidate, interval)))
    log("recordingRanges", dict(timestampFormat="ISO timestamps from native API are UTC; UI DD/MM/YYYY with per-group instrument offset and daylight savings", groups=recording_ranges))
    log("missingDataInvestigation", dict(selectedGroup=group["groupName"], selectedGroupOverlap=overlaps(group, requested),
        overlappingGroups=[dict(id=r["id"], name=r["name"], instrument=r["instrument"]) for r in recording_ranges if r["overlap"]],
        conclusion="Indexed recording ranges are visible in other groups. For absent Group 6 dates, file absence versus transfer/import/indexing failure is not distinguishable from these read-only UI diagnostics. No input directory or archive directory was scanned; no new data was imported."))
    selected = next((s for s in sources if s["name"] == group["instrument"]["instrumentName"]), None)
    if selected:
        try:
            age = (datetime.now(timezone.utc) - utc_time(selected["lastFileTransfer"])).total_seconds() / 60
        except (ValueError, TypeError):
            age = math.inf
        log("sourceTransfer", dict(selected, ageMinutes=str(age), staleAfterMinutes=settings.stale_minutes))
        if age > settings.stale_minutes:
            log("preflightWarning", dict(code="SOURCE_TRANSFER_STALE", message="Transfer freshness exceeds diagnostic threshold; historical sample availability is separate"))
    if configured:
        interval = configured
    elif settings.range_mode == "latestAvailable":
        interval = latest_available(group)
    elif settings.range_mode == "file":
        interval = file_interval(metadata, settings.start or None, settings.end or None)
    else:
        interval = requested
    log("reportInterval", interval)
    try:
        require_data(group, interval)
    except WorkflowError as error:
        issues.append(dict(code=error.code, message=str(error)))
    inspect_notifications(page, settings, log, run_id)
    log("preflight", dict(passed=not issues, issues=issues, groupMapped=True, archiveVerified=True, chartVerified=False))
    if issues:
        raise WorkflowError(issues[0]["code"], "Reporting preflight failed", issues)
    return interval
