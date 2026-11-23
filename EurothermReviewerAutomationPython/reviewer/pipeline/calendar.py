"""Recording-date discovery and non-destructive organization."""
import os
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common.time import utc_time, iso
from ..instrument.validation import validate_file, hash_file
from ..instrument.metadata import read_interval

MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def client_zone():
    # Asia/Kolkata uses no daylight-saving transitions; avoid a new tzdata dependency on Windows.
    name = os.environ.get('CLIENT_TIMEZONE', 'Asia/Kolkata')
    return timezone(timedelta(hours=5, minutes=30)) if name in {'Asia/Kolkata', 'Asia/Calcutta'} else ZoneInfo(name)


def date_folder(root, day):
    return root / str(day.year) / MONTHS[day.month - 1] / f'{day.day:02d}'


def discover(root):
    resolved = root.resolve()
    return sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink()
                  and p.suffix.lower() == '.uhh' and p.resolve().is_relative_to(resolved))


def daily_intervals(metadata, now=None):
    zone = client_zone()
    first, last = utc_time(metadata['FirstSample']), utc_time(metadata['LastSample'])
    if first >= last:
        raise ValueError('Recording timestamps do not define a usable interval')
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    if last.astimezone(zone).date() >= today:
        return []  # Defer the whole input while it contains current/future-day samples.
    intervals = []
    day = first.astimezone(zone).date()
    while day <= last.astimezone(zone).date():
        start = max(first, datetime.combine(day, time.min, zone).astimezone(timezone.utc))
        end = min(last, datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc))
        if start < end:
            intervals.append(dict(date=day.isoformat(), start=iso(start), end=iso(end)))
        day += timedelta(days=1)
    return intervals


def organize(source, root, first_day, sha):
    target = date_folder(root, first_day) / source.name
    if source.resolve() == target.resolve():
        return source
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or hash_file(target) != sha:
            raise ValueError(f'Input filename collision; existing file preserved: {target}')
        return target
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, suffix='.part')
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        shutil.copyfile(source, temporary)
        if hash_file(temporary) != sha or validate_file(source)['sha256'] != sha:
            raise ValueError('Source changed during organization; original left unchanged')
        os.link(temporary, target)  # Exclusive publication; never overwrite a concurrent file.
        return target
    finally:
        temporary.unlink(missing_ok=True)


def scan(settings, root, organize_inputs=False, now=None, stop_callback=None, on_file=None):
    records, seen = [], set()
    for source in discover(root):
        if stop_callback:
            stop_callback()
        if on_file:
            on_file(str(source))
        record = dict(source=str(source), status='Failed', tasks=[])
        try:
            verified = validate_file(source)
            record['sha256'] = verified['sha256']
            if verified['sha256'] in seen:
                record.update(status='Skipped', reason='Duplicate content')
            else:
                metadata = read_interval(replace(settings, file=source))
                if validate_file(source)['sha256'] != verified['sha256']:
                    raise ValueError('Input changed while metadata was being read')
                intervals = daily_intervals(metadata, now)
                record.update(metadata=metadata, tasks=intervals)
                if not intervals:
                    record.update(status='Skipped', reason='Current/future-day recording; deferred')
                else:
                    if organize_inputs:
                        from datetime import date
                        record['source'] = str(organize(source, root, date.fromisoformat(intervals[0]['date']), verified['sha256']))
                    record['status'] = 'Pending'
                seen.add(verified['sha256'])
        except Exception as error:
            record['reason'] = str(error)
        records.append(record)
    return records
