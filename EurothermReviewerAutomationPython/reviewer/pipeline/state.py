"""SQLite claims and verified report evidence shared across batch restarts."""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from ..common.time import now_iso
from ..instrument.validation import hash_file


class ProcessingState:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, source TEXT, day TEXT, state TEXT, attempts INTEGER, owner INTEGER, updated TEXT, detail TEXT)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def key(identity):
        return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()

    def claim(self, key, source, day, retries=0):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state, attempts, detail FROM tasks WHERE id=?', (key,)).fetchone()
            if row:
                state, attempts, detail = row
                saved = json.loads(detail)
                if state == 'Completed' and self.verified(saved.get('outputs', []), saved.get('channels', 1)):
                    return False
                if state == 'Running':
                    raise RuntimeError('Interrupted or active task claim exists; verify its owning process before recovery')
                if state == 'Failed' and attempts >= retries + 1:
                    return False
            attempts = row[1] + 1 if row else 1
            db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?)',
                       (key, str(source), day, 'Running', attempts, os.getpid(), now_iso(), '{}'))
        return True

    @staticmethod
    def verified(outputs, channels=1):
        """`channels` is 1 for combined reports, or the approved channel count when split by channel."""
        from pathlib import Path
        # A day without messages completes with the channel and pen reports and one explicit message-log skip.
        skipped = [o for o in outputs if o.get('status') == 'SKIPPED_NO_MESSAGES']
        reports = [o for o in outputs if o.get('status') != 'SKIPPED_NO_MESSAGES']
        if any(o.get('profile') != 'message-log' for o in skipped) or len(skipped) > 1:
            return False
        if type(channels) is not int or channels < 1 or len(reports) != (2 if skipped else 3) * channels:
            return False
        try:
            return len({o['output'] for o in reports}) == len(reports) and all(Path(o['output']).is_file() and hash_file(o['output']) == o['sha256'] for o in reports)
        except (OSError, KeyError):
            return False

    def finish(self, key, state, detail):
        if state == 'Completed' and not self.verified(detail.get('outputs', []), detail.get('channels', 1)):
            raise ValueError('Completion requires every verified report')
        with self.connect() as db:
            db.execute('UPDATE tasks SET state=?, updated=?, detail=? WHERE id=?', (state, now_iso(), json.dumps(detail), key))

    def get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT source,day,state,attempts,owner,detail FROM tasks WHERE id=?', (key,)).fetchone()
        return dict(source=row[0], date=row[1], status=row[2], attempts=row[3], owner=row[4], detail=json.loads(row[5])) if row else None
