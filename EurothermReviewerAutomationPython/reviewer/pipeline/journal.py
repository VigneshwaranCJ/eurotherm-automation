"""Content-bound checkpoints: only verified existing exports can be reused."""
import hashlib
import json
from ..instrument.validation import hash_file


class ExportJournal:
    def __init__(self, folder, identity):
        folder.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
        self.path = folder / f'{key}.json'
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def run_folder(self, run_id):
        """Reports with the same identity share one folder; it is saved with the first commit."""
        return self.data.setdefault('runFolder', run_id)

    def cached(self, profile, folder=None):
        """Reuse only a verified report, and when `folder` is given only one already in it."""
        from pathlib import Path
        item = self.data.get(profile)
        if item and folder is not None and Path(item['output']).parent.resolve() != Path(folder).resolve():
            return None
        if item and Path(item['output']).is_file() and hash_file(item['output']) == item['sha256']:
            extra = item.get('supplementary')
            if extra and not (Path(extra['output']).is_file() and hash_file(extra['output']) == extra['sha256']):
                return None
            return item
        return None

    def commit(self, profile, result):
        self.data[profile] = dict(result, sha256=hash_file(result['output']))
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        temporary.replace(self.path)
