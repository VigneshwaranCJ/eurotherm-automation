from datetime import timedelta
import re
from .common.errors import WorkflowError
from .common.time import iso, now_iso, utc_time


def configured_interval(start, end):
    def parse(value):
        pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})"
        if not re.fullmatch(pattern, value):
            raise WorkflowError("INVALID_INTERVAL", "Env dates must be ISO timestamps with seconds and an explicit timezone")
        try:
            if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
                raise ValueError("Invalid timezone offset")
            return iso(utc_time(value))
        except ValueError as error:
            raise WorkflowError("INVALID_INTERVAL", "Env timestamp contains an invalid date or time") from error
    result = dict(start=parse(start), end=parse(end), mode="env", historical=False)
    if utc_time(result["start"]) >= utc_time(result["end"]):
        raise WorkflowError("INVALID_INTERVAL", "END_DATETIME must be later than START_DATETIME")
    return result


def overlaps(group, interval):
    return utc_time(group["dataStart"]) < utc_time(interval["end"]) and utc_time(group["dataEnd"]) > utc_time(interval["start"])


def require_data(group, interval):
    try:
        start, end = utc_time(interval["start"]), utc_time(interval["end"])
        if start >= end or (interval["mode"] == "yesterday" and end - start != timedelta(days=1)):
            raise ValueError("Invalid interval or daylight-saving transition")
    except (ValueError, TypeError) as error:
        raise WorkflowError("INVALID_INTERVAL", "Invalid report interval; yesterday must be exactly 24 hours") from error
    if not overlaps(group, interval):
        raise WorkflowError("MISSING_DATA", "Selected group has no recording range overlapping the requested dates. "
                            + describe_gap(group, interval), interval)


def describe_gap(group, interval):
    """Say which side does not overlap, in the record's local time, e.g. 'starts 13 h 56 min after the last data'."""
    from datetime import timezone
    try:
        zone = timezone(timedelta(milliseconds=int(group.get("timezoneOffset") or 0)))
        first, last = utc_time(group["dataStart"]), utc_time(group["dataEnd"])
        start, end = utc_time(interval["start"]), utc_time(interval["end"])
    except (KeyError, TypeError, ValueError):
        return "The record's data range could not be read."
    offset = zone.utcoffset(None)
    label = "UTC" if not offset else f"UTC{'+' if offset >= timedelta(0) else '-'}{abs(offset) // timedelta(hours=1):02d}:{abs(offset) % timedelta(hours=1) // timedelta(minutes=1):02d}"

    def show(value):
        return value.astimezone(zone).strftime("%d/%m/%Y %H:%M")

    def span(delta):
        minutes = int(delta.total_seconds() // 60)
        days, rest = divmod(minutes, 1440)
        parts = [f"{days} d" if days else "", f"{rest // 60} h" if rest // 60 else "", f"{rest % 60} min" if rest % 60 else ""]
        return " ".join(p for p in parts if p) or "0 min"
    text = (f"Requested {show(start)} to {show(end)}; {group.get('groupName', 'the record')} has data from "
            f"{show(first)} to {show(last)} ({label}). ")
    if start >= last:
        return text + f"The whole range is after the last data: it starts {span(start - last)} after the data ends."
    if end <= first:
        return text + f"The whole range is before the first data: it ends {span(first - end)} before the data starts."
    return text + "The range does not overlap the recorded data."


def latest_available(group):
    try:
        start, end = utc_time(group["dataStart"]), utc_time(group["dataEnd"])
        if end <= start:
            raise ValueError("Empty range")
    except (ValueError, TypeError) as error:
        raise WorkflowError("MISSING_DATA", "No valid historical recording range") from error
    return dict(start=iso(max(start, end - timedelta(minutes=15))), end=iso(end), mode="latestAvailable", historical=True)


def file_interval(metadata, start=None, end=None):
    start, end = start or metadata["FirstSample"], end or metadata["LastSample"]
    try:
        if not (utc_time(metadata["FirstSample"]) <= utc_time(start) < utc_time(end) <= utc_time(metadata["LastSample"])):
            raise ValueError("Outside UHH recording")
    except (ValueError, TypeError) as error:
        raise WorkflowError("INVALID_INTERVAL", "File-validation report must remain within the specified UHH recording interval") from error
    return dict(start=start, end=end, mode="file", historical=True)


def verify_import_interval(page, settings, metadata, groups, log):
    """Stop before an irreversible import when the input cannot serve the requested report."""
    if settings.range_mode == "latestAvailable":
        return None  # Derived from the recording itself, so the input always supplies it.
    if settings.range_mode == "env":
        interval = configured_interval(settings.start, settings.end)
    elif settings.range_mode == "file":
        interval = file_interval(metadata, settings.start or None, settings.end or None)
    else:
        from .instrument.identity import identity_candidates
        candidates = identity_candidates(groups, metadata)
        if not candidates:
            raise WorkflowError("INTERVAL_UNVERIFIED", "Cannot verify yesterday's interval before import: Reviewer has no matching group or timezone")
        interval = yesterday_interval(page, candidates[0])
    recorded = dict(dataStart=metadata["FirstSample"], dataEnd=metadata["LastSample"])
    if not overlaps(recorded, interval):
        raise WorkflowError("INTERVAL_OUTSIDE_INPUT", "The requested report dates are outside this input file; nothing was imported",
                            dict(requested=interval, recorded=recorded))
    log("importIntervalVerified", dict(requested=interval, recorded=recorded))
    return interval


def yesterday_interval(page, group, now=None):
    return page.evaluate("""({group, now}) => {
        const settings = window.moment.createSettings(group.timezoneOffset, group.daylightSavings);
        const utcNow = window.moment.utc(now);
        const today = utcNow.clone().utcOffset(window.moment.calculateOffset(utcNow, settings)).startOf('day');
        const yesterday = today.clone().subtract(1, 'day');
        const midnight = m => {
            const wall = window.moment.utc(m.format('YYYY-MM-DD') + 'T00:00:00');
            for (let i=0; i<3; i++) wall.utcOffset(window.moment.calculateOffset(wall, settings), true);
            return wall;
        };
        const start = midnight(yesterday), end = midnight(today);
        return {start:start.toISOString(), end:end.toISOString(), mode:'yesterday', historical:false,
            displayStart:start.format('DD/MM/YYYY HH:mm:ss Z'), displayEnd:end.format('DD/MM/YYYY HH:mm:ss Z'), dateSettings:settings};
    }""", {"group": group, "now": now or now_iso()})
