"""Report Include options and naming independent of browser operations."""
from dataclasses import replace
import re


def safe_name(value):
    name = re.sub(r'[^A-Za-z0-9_-]+', '-', value).strip('-')[:80]
    if not name:
        raise ValueError('Export name is empty after normalization')
    return name


SUBFOLDERS = {'graph': 'channel', 'pen-log': 'pen', 'message-log': 'message'}


def profile_folder(settings, profile, config, run_folder):
    if profile not in SUBFOLDERS:
        raise ValueError('Unknown report profile')
    if settings.recording_date:
        from datetime import date
        from .calendar import date_folder
        folder = date_folder(config.output_dir, date.fromisoformat(settings.recording_date)) / 'Reports' / settings.source_key
        return folder / SUBFOLDERS[profile] if getattr(config, 'split_by_channel', False) else folder
    return config.output_dir / safe_name(config.record_id) / safe_name(run_folder) / SUBFOLDERS[profile]


def channel_report_name(channel):
    """`channel` is (position in the approved list, exact name); the number keeps files in list order."""
    index, name = channel
    return f'{index:02d}_{safe_name(name)}.pdf'


def profile_settings(settings, profile, config, run_folder, channel=None):
    folder = profile_folder(settings, profile, config, run_folder)
    messages = profile == 'message-log'
    pen = profile == 'pen-log'
    report_name = ''
    if channel is not None:
        report_name = channel_report_name(channel)
    elif settings.recording_date:
        names = {'graph': 'Channels_Logs', 'pen-log': 'Pen_Logs', 'message-log': 'Message_Logs'}
        report_name = f'{safe_name(config.record_id)}_{names[profile]}.pdf'
    folder.mkdir(parents=True, exist_ok=True)
    title = f'{config.record_id} - {profile}'
    if settings.range_mode == 'latestAvailable':
        title += ' - HISTORICAL TEST REPORT'
    return replace(settings, reports=folder, report_name=report_name, title=title,
                   include_chart=not messages, include_values=pen,
                   include_messages=pen or messages, separate_messages=pen or messages,
                   cursor_statistics=True)
