"""Import verification, Custom selection, and resumable report orchestration."""
from dataclasses import replace

from ..instrument.metadata import read_interval
from ..instrument.identity import select_group, identity
from ..instrument.duplicates import import_evidence, check_duplicate
from ..instrument.importer import import_single_file
from ..ui.groups import all_groups
from ..ui.sources import inspect_sources
from ..ui.chart import open_chart
from ..health.preflight import run_preflight
from ..ranges import configured_interval, verify_import_interval
from ..reports.messages import SKIPPED_NO_MESSAGES, fetch_messages, write_filtered_messages
from ..reports.settings import configure_print
from ..reports.validation import report_date
from ..reports.preview import validate_preview
from ..reports.pdf import download_pdf
from .configuration import PipelineConfig
from .selection import select_record, select_channels
from .profiles import profile_folder, profile_settings
from .journal import ExportJournal


REPORT_ATTEMPTS = 2


def timed_out(error):
    """True when Reviewer did not answer in time, directly or as the cause of a Preview failure."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    while error is not None:
        if isinstance(error, PlaywrightTimeout):
            return True
        error = error.__cause__
    return False


def prepare_pipeline(settings):
    config = PipelineConfig.load()
    selected = config.select_input()
    return config, replace(settings, file=selected, reports=config.output_dir)


def execute_pipeline(command, settings, config, authorization, log, run_id, page):
    metadata = read_interval(settings)
    log('uhhMetadata', metadata)
    normal = all_groups(page)
    evidence = import_evidence(normal, metadata, settings.file)
    log('importEvidence', evidence)
    if evidence['status'] != 'already-imported':
        if command == 'workflow:preview':
            raise RuntimeError('Preview requires a verified existing import; use the authorized workflow:run command first')
        verify_import_interval(page, settings, metadata, normal, log)
        import_single_file(page, settings, authorization['sha'], evidence['status'] == 'uncertain', authorization['token'], log)
        normal = all_groups(page)
    source = select_group(normal, metadata, '')
    if check_duplicate(source, settings.file)['status'] != 'already-imported':
        raise RuntimeError('Imported data did not match the source hash; no automatic resubmission')
    log('inputLoaded', dict(sha256=authorization['sha'], group=source['groupId']))
    sources = inspect_sources(page, settings, log, run_id)
    custom = all_groups(page, custom=True)
    record = select_record(custom, config.record_id, config.record_field)
    segment, history = identity(metadata)
    instrument = record.get('instrument') or {}
    if instrument.get('instrumentName') != segment['InstrumentName'] or instrument.get('macAddress') != history['MacAddr']:
        raise ValueError('Custom record instrument identity does not match the selected UHH; mapping requires review')
    log('customRecordSelected', dict(recordId=config.record_id, field=config.record_field, groupId=record['groupId']))
    interval = configured_interval(settings.start, settings.end) if settings.range_mode == 'env' else None
    interval = run_preflight(page, record, custom, metadata, sources, settings, log, run_id, interval)
    journal = ExportJournal(settings.logs / 'export-journal', dict(
        inputSha256=authorization['sha'], config=config.summary(), mappings=config.channels,
        interval=interval, options=dict(cursor=config.cursor_statistics, paper=settings.paper,
                                       pages=settings.pages, major=settings.major, minor=settings.minor,
                                       rangeMode=settings.range_mode), output=str(config.output_dir), version=3))
    results = []
    profiles = {'workflow:channels': ('graph',), 'workflow:pen': ('pen-log',), 'workflow:messages': ('message-log',)}.get(command, ('graph', 'pen-log', 'message-log'))
    exporting = command != 'workflow:preview'
    run_folder = journal.run_folder(run_id)
    names = tuple(c['name'] for c in config.channels)
    # Combined: one report per type for all approved channels. Split: one report per type and channel.
    units = list(enumerate(names, 1)) if config.split_by_channel else [None]
    from .batch import check_stop
    for profile in profiles:
        check_stop()
        log('profileStarted', dict(profile=profile, reports=len(units)))
        messages = source_channels = None
        skipped = None
        for unit in units:
            check_stop()
            key = profile if unit is None else f'{profile}/{unit[0]:02d}'
            label = {} if unit is None else dict(channel=unit[1], channelIndex=unit[0])
            wanted = names if unit is None else (unit[1],)
            cached = journal.cached(key, profile_folder(settings, profile, config, run_folder)) if exporting else None
            if cached:
                log('pdfVerified', dict(cached, reused=True, profile=profile, **label))
                results.append(cached)
                continue
            step = f"{run_id}-{key.replace('/', '-')}"
            for attempt in range(1, REPORT_ATTEMPTS + 1):
                try:
                    groups = all_groups(page, custom=True)
                    current = select_record(groups, config.record_id, config.record_field)
                    if current['groupId'] != record['groupId']:
                        raise ValueError('Selected Custom record changed during execution')
                    chart = open_chart(page, current, interval, settings, log, step)
                    chart['deselectedChannels'] = [c['channelName'] for c in chart['channels'] if c['channelName'] not in wanted]
                    chart['channels'] = select_channels(page, chart['channels'], config.channels, wanted, log)
                    if profile == 'message-log':
                        if messages is None:
                            # Reviewer scopes messages to the record, so one query serves every channel.
                            messages, source_channels = fetch_messages(page, current, interval)
                        if not messages:
                            # Reviewer confirms none exist, and would render a blank Preview and no PDF.
                            instrument = current['instrument']
                            skipped = dict(status=SKIPPED_NO_MESSAGES, profile=profile, date=settings.recording_date or report_date(chart),
                                           start=interval['start'], end=interval['end'], record=current['groupName'],
                                           instrument=instrument['instrumentName'], macAddress=instrument.get('macAddress'),
                                           reason='Reviewer reports no messages for this interval; no empty PDF was generated')
                            log('messageLogSkipped', skipped)
                            results.append(skipped)
                            break
                    configured = profile_settings(settings, profile, config, run_folder, unit)
                    configure_print(page, configured, log)
                    validate_preview(page, current, chart, configured, log, step)
                    break
                except Exception as error:
                    # Only Reviewer not answering in time is retried; a report that fails a check never is.
                    if attempt == REPORT_ATTEMPTS or not timed_out(error):
                        raise
                    log('reportRetry', dict(profile=profile, attempt=attempt, reason=str(error), **label))
                    page.reload(wait_until='load', timeout=120000)
            if skipped:
                break
            if exporting:
                result = download_pdf(page, current, chart, configured, log)
                result.update(label)
                if messages:
                    result['supplementary'] = write_filtered_messages(result, messages, source_channels, wanted, current, interval, log)
                journal.commit(key, result)
                results.append(result)
            if unit is not None:
                log('channelReportComplete', dict(profile=profile, downloaded=exporting, **label, of=len(units)))
        if not skipped:
            log('profileComplete', dict(profile=profile, downloaded=exporting))
    log('workflowComplete', dict(profiles=len(profiles), outputs=results,
                                 skipped=[r['profile'] for r in results if r.get('status') == SKIPPED_NO_MESSAGES]))
    return results
