"""Persist UI launches and run the existing guarded CLI without a shell."""
import json
import subprocess
import sys
import os
import threading
import uuid
from pathlib import Path
from urllib.parse import quote
from collections import deque

from .config import ROOT
from .common.time import now_iso
from .common.events import iter_events

UI_COMMANDS = ('batch:scan', 'batch:organize', 'batch:run', 'input:import', 'report', 'report:dry', 'diagnostics', 'datasources', 'discover', 'file:check', 'workflow:preview', 'workflow:run', 'workflow:channels', 'workflow:pen', 'workflow:messages')


class RunManager:
    def __init__(self, settings):
        self.folder = settings.logs / 'ui-runs'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.process = None
        self.current_job = None
        # A prior API process cannot confirm its child's outcome after restart.
        for path in self.folder.glob('*.json'):
            job = json.loads(path.read_text(encoding='utf-8'))
            if job['status'] == 'Running':
                job.update(status='Unknown', message='API restarted; check logs before rerunning.')
                console = self.folder / (job['id'] + '.log')
                if console.exists():
                    for event in iter_events(console):
                        if event['event'] == 'failure':
                            job.update(status='Failed', finished=event.get('time'),
                                       message=(event.get('data') or {}).get('message', 'Automation failed'))
                        elif event['event'] == 'complete':
                            job.update(status='Success', finished=event.get('time'), message='Automation completed')
                self.save(job)

    def save(self, job):
        path = self.folder / (job['id'] + '.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(job), encoding='utf-8')
        temporary.replace(path)

    def start(self, command, input_sha=None):
        if command not in UI_COMMANDS:
            raise ValueError('Unsupported UI command')
        if command == 'batch:run':
            from .pipeline.configuration import PipelineConfig
            PipelineConfig.load()
        if command.startswith('workflow:'):
            from .pipeline.runner import prepare_pipeline
            from .config import Settings
            prepare_pipeline(Settings.load())
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError('Automation is already running. Wait for it to finish.')
            arguments = [sys.executable, '-u', '-m', 'reviewer', command]
            environment = dict(os.environ)
            staged = None
            if command == 'input:import' or command.startswith('workflow:'):
                from .pipeline.inputs import select_folder_input
                from .instrument.validation import validate_file
                selected = select_folder_input()
                verified = validate_file(selected)
                staged = dict(name=selected.name, path=str(selected), sha256=verified['sha256'])
                if input_sha is not None and input_sha != staged['sha256']:
                    raise ValueError('The selected input changed. Review the file before rerunning.')
                environment['TEST_UHH_FILE'] = staged['path']
                if command != 'workflow:preview':
                    environment['DRY_RUN'] = 'false'
                    arguments = [sys.executable, '-u', '-m', 'reviewer',
                                 'import:test' if command == 'input:import' else command,
                                 '--authorize-import=' + staged['sha256']]
            job = dict(id='ui-' + uuid.uuid4().hex, time=now_iso(), action=command,
                       status='Running', output=None, outputUrl=None, logUrl=None,
                       message='Automation started', exitCode=None, finished=None)
            if staged:
                job.update(inputName=staged['name'], inputSha256=staged['sha256'])
            if command.startswith('batch:'):
                environment['BATCH_STOP_FILE'] = str(self.folder / (job['id'] + '.stop'))
            console = self.folder / (job['id'] + '.log')
            with console.open('wb') as stream:
                self.process = subprocess.Popen(arguments, env=environment,
                                                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.save(job)
            self.current_job = job
            threading.Thread(target=self.finish, args=(job, self.process)).start()
            return job

    def finish(self, job, process):
        code = process.wait()
        with self.lock:
            job.update(status='Success' if code == 0 else 'Failed', exitCode=code,
                       finished=now_iso(), message='Automation completed' if code == 0 else 'Automation failed; see details and logs.')
            if code == 2 and job['action'].startswith('batch:'):
                job.update(status='Stopped', message='Stopped at a safe checkpoint; completed reports preserved')
            self.save(job)

    def stop(self):
        with self.lock:
            if not self.current_job or not self.current_job['action'].startswith('batch:') or self.process.poll() is not None:
                raise RuntimeError('No active batch can be stopped')
            (self.folder / (self.current_job['id'] + '.stop')).write_text('stop', encoding='utf-8')
            self.current_job['stopRequested'] = True
            self.save(self.current_job)
            return dict(message='Stop requested. Any active native operation will finish before the next checkpoint.')

    def records(self):
        with self.lock:
            jobs = [json.loads(p.read_text(encoding='utf-8')) for p in self.folder.glob('*.json')]
        files, run_logs = {}, set()
        for job in jobs:
            console = (self.folder / (job['id'] + '.log')).resolve()
            files[str(console)] = console
            job['logUrl'] = '/api/file?path=' + quote(str(console), safe='')
            events = deque(maxlen=20)
            job['outputs'] = []
            for event in iter_events(console):
                events.append(event)
                data = event.get('data') or {}
                if event['event'] == 'start' and data.get('runId'):
                    run_logs.add('run-' + data['runId'] + '.jsonl')
                if event['event'] == 'pdfVerified':
                    job['output'] = data.get('output')
                    if data.get('output'):
                        job['outputs'].append(dict(path=data['output'], reused=data.get('reused', False)))
                if event['event'] == 'supplementaryMessages':
                    job['outputs'].append(dict(path=data['output'], supplementary=True))
                if event['event'] == 'messageLogSkipped':
                    job['message'] = f"{data.get('status')}: {data.get('date')} {data.get('instrument')}. {data.get('reason')}"
                    if job['status'] == 'Success' and job['action'] == 'workflow:messages':
                        job['status'] = data.get('status')
                if event['event'] == 'failure':
                    job['message'] = data.get('message', job['message'])
            job['details'] = list(events)
        return jobs, files, run_logs
