"""Stream one staged UHH input; native import is a separate explicit action."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .config import ROOT, WORKSPACE

MAX_UPLOAD = 256 * 1024 * 1024
UPLOAD_FOLDER = WORKSPACE / 'Input_uhh_files'
UPLOAD_STATE = ROOT / '.tmp' / 'ui-upload.json'


def selected_upload():
    if not UPLOAD_STATE.is_file():
        return None
    data = json.loads(UPLOAD_STATE.read_text(encoding='utf-8'))
    path = Path(data['path']).resolve()
    if path.parent != UPLOAD_FOLDER.resolve() or not path.is_file() or path.is_symlink():
        raise ValueError('Previously uploaded file is unavailable; upload it again')
    return data


def store_upload(stream, size, filename):
    if not 0 < size <= MAX_UPLOAD:
        raise ValueError('Choose a nonempty file up to 256 MB')
    if (not filename or len(filename) > 180 or Path(filename).name != filename
            or any(c in filename for c in '/\\:*?"<>|\r\n') or Path(filename).suffix.lower() != '.uhh'):
        raise ValueError('Choose one .UHH file with a valid filename')
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    UPLOAD_STATE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(suffix='.part', dir=UPLOAD_FOLDER)
    temporary = Path(temporary)
    try:
        digest, remaining = hashlib.sha256(), size
        with os.fdopen(descriptor, 'wb') as output:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('Upload was interrupted; please try again')
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        sha = digest.hexdigest()
        destination = UPLOAD_FOLDER / filename
        if destination.exists():
            from .instrument.validation import hash_file
            if destination.is_symlink() or hash_file(destination) != sha:
                raise ValueError('A different file with this name already exists. Rename your file before uploading; existing data was preserved.')
        else:
            # Exclusive publication preserves a concurrently created input.
            os.link(temporary, destination)
        state = dict(name=filename, path=str(destination.resolve()), sha256=sha, size=size)
        pending = UPLOAD_STATE.with_suffix('.tmp')
        pending.write_text(json.dumps(state), encoding='utf-8')
        pending.replace(UPLOAD_STATE)
        return state
    finally:
        temporary.unlink(missing_ok=True)
