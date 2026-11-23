"""Explicit, reviewable configuration for the approved-channel workflow.

Combined reports need exactly 25 approved channels. With split_by_channel, every approved
channel (up to MAX_SPLIT_CHANNELS) gets its own PDF for each report type.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT, WORKSPACE, inside_root

COMBINED_CHANNELS = 25
MAX_SPLIT_CHANNELS = 100


@dataclass(frozen=True)
class PipelineConfig:
    input_dir: Path
    output_dir: Path
    filename: str
    record_id: str
    record_field: str
    channels: tuple
    graph_channels: tuple
    cursor_statistics: bool
    split_by_channel: bool = False

    @classmethod
    def load(cls, filename=None):
        path = inside_root(filename or os.environ.get('WORKFLOW_CONFIG', str(ROOT / 'workflow.json')))
        if not path.is_file():
            raise ValueError(f'Missing workflow configuration: copy workflow.example.json to {path} and complete the record/channel mapping')
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('Workflow configuration must be a JSON object')
        split = data.get('split_by_channel', False)
        if type(split) is not bool:
            raise ValueError('split_by_channel must be boolean')
        channels = data.get('channels', [])
        if not isinstance(channels, list) or not all(isinstance(c, dict) for c in channels):
            raise ValueError('channels must be a list of name/selector mappings')
        if split and not 1 <= len(channels) <= MAX_SPLIT_CHANNELS:
            raise ValueError(f'split_by_channel requires 1 to {MAX_SPLIT_CHANNELS} approved channel mappings')
        if not split and len(channels) != COMBINED_CHANNELS:
            raise ValueError('Exactly 25 approved channel mappings are required')
        names = [c.get('name') for c in channels]
        if any(not isinstance(v, str) or not v.strip() for v in names):
            raise ValueError('Each channel requires an exact native name')
        if len(set(names)) != len(names):
            raise ValueError('Channel names must be unique')
        record_id, record_field = data.get('record_id'), data.get('record_field')
        if not record_id or record_field not in {'groupName', 'instrument.instrumentName'}:
            raise ValueError('Set record_id and an approved record_field: groupName or instrument.instrumentName')
        graph = data.get('graph_channels', names)
        if not isinstance(graph, list) or not all(isinstance(name, str) for name in graph):
            raise ValueError('graph_channels must be a list of channel names')
        if len(graph) != len(names) or set(graph) != set(names):
            raise ValueError(f'Channels Logs must select all {len(names)} approved channel names individually')
        cursor = data.get('cursor_statistics', True)
        if type(cursor) is not bool:
            raise ValueError('cursor_statistics must be boolean')
        selected_file = data.get('input_file', '')
        if selected_file and (Path(selected_file).name != selected_file or '/' in selected_file or '\\' in selected_file):
            raise ValueError('input_file must be a filename within input_dir')
        return cls(inside_root(data.get('input_dir', str(WORKSPACE / 'Input_uhh_files'))),
                   inside_root(data.get('output_dir', str(WORKSPACE / 'Output_report_files'))),
                   selected_file, record_id, record_field, tuple(channels), tuple(graph), cursor, split)

    def select_input(self):
        from .inputs import select_unique_input
        return select_unique_input(self.input_dir, self.filename)

    def identity(self):
        """Values that define the reports; the split flag appears only when on, so combined runs keep their checkpoints."""
        from dataclasses import asdict
        values = asdict(self)
        if not self.split_by_channel:
            values.pop('split_by_channel')
        return values

    def summary(self):
        result = dict(inputDirectory=str(self.input_dir), outputDirectory=str(self.output_dir),
                      recordId=self.record_id, recordField=self.record_field,
                      channelCount=len(self.channels), graphChannels=list(self.graph_channels),
                      profiles=['graph', 'pen-log', 'message-log'], importRequiresShaAuthorization=True)
        if self.split_by_channel:
            result.update(splitByChannel=True, reportsPerRun=3 * len(self.channels))
        return result


def inspect_plan():
    result = dict(ready=False, mappingReady=False, inputDirectory=str(WORKSPACE / 'Input_uhh_files'),
                  outputDirectory=str(WORKSPACE / 'Output_report_files'), issues=[])
    try:
        # Show the folders actually in use even while the channel mapping is incomplete.
        from .inputs import workflow_folders
        result['inputDirectory'], result['outputDirectory'] = map(str, workflow_folders())
        config = PipelineConfig.load()
        result.update(config.summary())
        result['mappingReady'] = True
        result['selectedInput'] = str(config.select_input())
        result['ready'] = True
    except (ValueError, OSError, TypeError, KeyError) as error:
        result['issues'].append(str(error))
    directory = Path(result['inputDirectory'])
    from .calendar import discover
    result['inputFiles'] = [str(p.relative_to(directory)) for p in discover(directory)]
    if not result['inputFiles']:
        result['ready'] = False
        result['issues'].append(f'No .UHH files found in {directory}')
    return result
