"""Resolve workflow folders and one folder-based input without a browser upload step."""
import json
import os
from ..config import ROOT, WORKSPACE, inside_root
from ..instrument.validation import hash_file


def read_workflow_file():
    path = inside_root(os.environ.get('WORKFLOW_CONFIG', str(ROOT / 'workflow.json')))
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('Workflow configuration must be a JSON object')
    return data


def workflow_folders():
    data = read_workflow_file()
    return (inside_root(data.get('input_dir', str(WORKSPACE / 'Input_uhh_files'))),
            inside_root(data.get('output_dir', str(WORKSPACE / 'Output_report_files'))))


def select_unique_input(folder, filename=''):
    """Choose one input by content, so batch:organize's dated copies are not seen as extra files.

    Identical copies count once and the shallowest path is used; different content is never guessed.
    """
    from .calendar import discover
    files = discover(folder)
    if filename:
        files = [p for p in files if p.name == filename]
    distinct = {hash_file(p) for p in files} if len(files) > 1 else files
    if len(distinct) != 1:
        raise ValueError(f'Expected one selected .UHH file in {folder}; found {len(distinct)}. Set input_file when multiple files exist.')
    return min(files, key=lambda path: (len(path.parts), str(path)))


def select_folder_input():
    data = read_workflow_file()
    return select_unique_input(workflow_folders()[0], data.get('input_file', ''))
