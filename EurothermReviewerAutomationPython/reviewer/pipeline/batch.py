"""Sequential recording-day queue using the existing guarded native workflow."""
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

from ..config import ROOT
from ..common.time import now_iso
from ..instrument.validation import hash_file
from .configuration import PipelineConfig
from .calendar import scan, date_folder
from .inputs import workflow_folders
from .profiles import safe_name
from .state import ProcessingState

STATUS = ROOT / '.tmp' / 'batch-status.json'
DATABASE = ROOT / '.tmp' / 'processing.sqlite'


class BatchStopped(RuntimeError):
    pass


def check_stop():
    marker = os.environ.get('BATCH_STOP_FILE')
    if marker and Path(marker).is_file():
        raise BatchStopped('Stop requested; previous completed exports are preserved')


def roots():
    return workflow_folders()


def snapshot(data):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(data, updated=now_iso()), indent=2), encoding='utf-8')
    temporary.replace(STATUS)


def batch_status():
    return json.loads(STATUS.read_text(encoding='utf-8')) if STATUS.is_file() else None


def write_manifest(folder, key, entry):
    path = folder / 'processing_manifest.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    data[key] = entry
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def run_batch(settings, command):
    from ..application.run import run_command
    from ..common.locking import run_lock
    settings.prepare()
    config = PipelineConfig.load() if command == 'batch:run' else None
    input_root, output_root = roots()
    settings.temp.mkdir(parents=True, exist_ok=True)
    with run_lock(settings.temp / 'batch.lock'):
        info = dict(status='Scanning', currentFile=None, totalFiles=0, completedFiles=0, failedFiles=0, skippedFiles=0, files=[])
        snapshot(info)
        def scanning_file(path):
            info.update(currentFile=path, phase='Reading verified recording dates')
            snapshot(info)
        try:
            check_stop()
            records = scan(settings, input_root, organize_inputs=command != 'batch:scan', stop_callback=check_stop, on_file=scanning_file)
        except BatchStopped:
            info.update(status='Stopped', currentFile=None)
            snapshot(info)
            return info
        if command != 'batch:scan':
            for record in records:
                for interval in record['tasks'] if record['status'] == 'Pending' else []:
                    day_root = date_folder(output_root, date.fromisoformat(interval['date']))
                    (day_root / 'Reports').mkdir(parents=True, exist_ok=True)
                    (day_root / 'Logs').mkdir(parents=True, exist_ok=True)
                    with (day_root / 'Logs/execution.log').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(dict(time=now_iso(), event='inputDiscovered', data=dict(source=record['source'], recordingDate=interval['date'], sha256=record['sha256']))) + '\n')
        output_root.mkdir(parents=True, exist_ok=True)
        state = ProcessingState(DATABASE)
        info = dict(status='Scanned', currentFile=None, totalFiles=len(records), completedFiles=0,
                    failedFiles=sum(r['status'] == 'Failed' for r in records),
                    skippedFiles=sum(r['status'] == 'Skipped' for r in records), files=records)
        snapshot(info)
        discovery = output_root / 'Logs'
        discovery.mkdir(parents=True, exist_ok=True)
        (discovery / 'discovery.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        if command != 'batch:run':
            print(json.dumps(dict(event='batchScanned', data=info)), flush=True)
            return info
        retries = int(os.environ.get('BATCH_MAX_RETRIES', '0'))
        if not 0 <= retries <= 3:
            raise ValueError('BATCH_MAX_RETRIES must be between 0 and 3')
        info['status'] = 'Running'
        try:
            for record in records:
                check_stop()
                if record['status'] != 'Pending':
                    continue
                outcomes = []
                for interval in record['tasks']:
                    check_stop()
                    day_logs = date_folder(output_root, date.fromisoformat(interval['date'])) / 'Logs'
                    day_logs.mkdir(parents=True, exist_ok=True)
                    identity = dict(sha=record['sha256'], interval=interval, config=config.identity(),
                                    paper=settings.paper, pages=settings.pages, major=settings.major, minor=settings.minor, version=4)
                    key = state.key(identity)
                    info.update(currentFile=record['source'], recordingDate=interval['date'], phase='Checking import',
                                profiles={'graph': 'Pending', 'pen-log': 'Pending', 'message-log': 'Pending'})
                    snapshot(info)
                    while True:
                        if not state.claim(key, record['source'], interval['date'], retries):
                            previous = state.get(key)['status']
                            outcomes.append(previous)
                            if previous == 'Completed':
                                info.update(phase='Verified exports reused', profiles={p: 'Completed' for p in ('graph', 'pen-log', 'message-log')})
                            break
                        try:
                            check_stop()
                            daily = replace(settings, file=Path(record['source']), logs=day_logs,
                                            reports=output_root, recording_date=interval['date'],
                                            source_key=safe_name(Path(record['source']).stem) + '_' + record['sha256'][:12],
                                            range_mode='env', start=interval['start'], end=interval['end'], dry_run=False)
                            def progress(event, data):
                                phases = {'fileVerified': 'Input verified', 'importEvidence': 'Checking import',
                                          'inputLoaded': 'Import verified', 'customRecordSelected': 'Custom record selected',
                                          'channelsSelected': 'Channels selected', 'printSettings': 'Report options verified',
                                          'preview': 'Preview verified', 'pdfVerified': 'Report verified', 'failure': 'Failed'}
                                if event == 'profileStarted':
                                    info['activeProfile'] = data['profile']
                                    info['profiles'][data['profile']] = 'Running'
                                elif event == 'profileComplete' or event == 'pdfVerified' and data.get('reused'):
                                    info['profiles'][data['profile']] = 'Completed'
                                elif event == 'messageLogSkipped':
                                    info['profiles'][data['profile']] = data['status']
                                    info['skippedReports'] = info.get('skippedReports', 0) + 1
                                elif event == 'failure' and info.get('activeProfile'):
                                    info['profiles'][info['activeProfile']] = 'Failed'
                                if event in phases:
                                    info['phase'] = phases[event]
                                if event in phases or event in {'profileStarted', 'profileComplete', 'messageLogSkipped'}:
                                    snapshot(info)
                            outputs = run_command('workflow:run', daily, record['sha256'], pipeline_config=config, on_event=progress)
                            evidence = [dict(o, sha256=hash_file(o['output'])) if 'output' in o else o for o in outputs]
                            completed = dict(outputs=evidence)
                            if config.split_by_channel:
                                completed['channels'] = len(config.channels)
                            state.finish(key, 'Completed', completed)
                            outcomes.append('Completed')
                            break
                        except BatchStopped as error:
                            state.finish(key, 'Stopped', dict(message=str(error)))
                            write_manifest(day_logs, key, state.get(key))
                            raise
                        except Exception as error:
                            state.finish(key, 'Failed', dict(message=str(error)))
                            print(json.dumps(dict(event='batchTaskFailed', data=dict(source=record['source'], date=interval['date'], message=str(error)))), flush=True)
                            if state.get(key)['attempts'] >= retries + 1:
                                outcomes.append('Failed')
                                break
                    write_manifest(day_logs, key, state.get(key))
                record['status'] = 'Completed' if outcomes and all(s == 'Completed' for s in outcomes) else 'Failed'
                info['completedFiles'] += int(record['status'] == 'Completed')
                info['failedFiles'] += int(record['status'] == 'Failed')
                snapshot(info)
            info.update(status='Failed' if info['failedFiles'] else 'Completed', currentFile=None)
        except BatchStopped:
            info.update(status='Stopped', currentFile=None)
        except Exception as error:
            info.update(status='Failed', currentFile=None, error=str(error))
            raise
        finally:
            snapshot(info)
        print(json.dumps(dict(event='batchComplete', data=info)), flush=True)
        return info
