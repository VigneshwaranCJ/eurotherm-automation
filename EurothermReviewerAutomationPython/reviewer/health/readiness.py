"""Pure disk and indexing readiness decisions."""
import math


def readiness_issues(status, disks=()):
    issues = []
    try:
        minimum, available = float(status["settings_MinFreeDiskSpace"]), float(status["freeDiskSize"])
        if not math.isfinite(minimum) or not math.isfinite(available):
            raise ValueError("Unknown disk status")
        windows_free = next((d["freeGB"] for d in disks if d["drive"] == "C:\\"), None)
        if available < minimum or (windows_free is not None and windows_free < minimum):
            issues.append(dict(code="LOW_DISK_SPACE", message=f"C: free {available:.2f} GB; required {minimum} GB"))
    except (ValueError, TypeError, KeyError):
        issues.append(dict(code="STATUS_UNAVAILABLE", message="Reviewer disk threshold or available space is unknown"))
    if status.get("indexingEnable") is not True:
        issues.append(dict(code="INDEXING_DISABLED", message="Reviewer indexing is disabled"))
    return issues
