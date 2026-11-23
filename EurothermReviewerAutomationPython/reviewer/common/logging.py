"""Timestamped JSON execution evidence."""
import json
from .time import now_iso


def create_logger(folder, run_id, mirror=None, observer=None):
    filename = folder / f"run-{run_id}.jsonl"
    def log(event, data=None):
        entry = {"time": now_iso(), "event": event, "data": data}
        with filename.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        if mirror:
            with (folder / mirror).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
        print(json.dumps(entry, ensure_ascii=True, default=str), flush=True)
        if observer:
            observer(event, data)
    return log
