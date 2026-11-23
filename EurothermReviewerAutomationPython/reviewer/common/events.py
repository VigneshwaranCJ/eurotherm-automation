"""Stream JSON log events without loading an entire console transcript."""
import json


def iter_events(path):
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                event = json.loads(line)
                if isinstance(event, dict) and 'event' in event:
                    yield event
            except json.JSONDecodeError:
                continue
