"""UTC parsing and formatting."""
from datetime import datetime, timezone


def utc_time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso():
    return iso(datetime.now(timezone.utc))
