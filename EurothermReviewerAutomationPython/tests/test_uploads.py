import hashlib
import io
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from reviewer.config import WORKSPACE
from reviewer.uploads import store_upload, selected_upload
from reviewer.ui_runs import RunManager


class UploadTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch('reviewer.uploads.UPLOAD_FOLDER', self.root / 'inputs'))
        stack.enter_context(patch('reviewer.uploads.UPLOAD_STATE', self.root / 'state/selected.json'))

    def test_upload_preserves_name_hash_and_selection(self):
        content = b'fixture UHH bytes'
        saved = store_upload(io.BytesIO(content), len(content), 'record.uhh')
        self.assertEqual(Path(saved['path']).read_bytes(), content)
        self.assertEqual(saved['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(selected_upload(), saved)
        self.assertEqual(store_upload(io.BytesIO(content), len(content), 'record.uhh'), saved)

    def test_different_content_never_overwrites_existing_file(self):
        saved = store_upload(io.BytesIO(b'original'), 8, 'record.uhh')
        with self.assertRaisesRegex(ValueError, 'different file'):
            store_upload(io.BytesIO(b'changed'), 7, 'record.uhh')
        self.assertEqual(Path(saved['path']).read_bytes(), b'original')

    def test_bad_types_paths_sizes_and_interrupted_upload_are_rejected(self):
        for name in ['../bad.uhh', 'bad.txt', 'C:\\bad.uhh', 'bad\n.uhh']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                store_upload(io.BytesIO(b'data'), 4, name)
        for size in [0, 257 * 1024 * 1024]:
            with self.assertRaises(ValueError):
                store_upload(io.BytesIO(), size, 'record.uhh')
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            store_upload(io.BytesIO(b'x'), 20, 'record.uhh')
        self.assertEqual(list((self.root / 'inputs').glob('*')), [])

    def test_import_uses_uploaded_hash_as_explicit_authorization(self):
        saved = store_upload(io.BytesIO(b'record'), 6, 'record.uhh')
        manager = RunManager(SimpleNamespace(logs=self.root / 'logs'))
        with patch('reviewer.ui_runs.subprocess.Popen') as launch, patch('reviewer.ui_runs.threading.Thread'), patch('reviewer.pipeline.inputs.select_folder_input', return_value=Path(saved['path'])), patch('reviewer.instrument.validation.validate_file', return_value={'sha256': saved['sha256']}):
            with self.assertRaisesRegex(ValueError, 'input changed'):
                manager.start('input:import', input_sha='different')
            job = manager.start('input:import', input_sha=saved['sha256'])
        self.assertEqual(launch.call_args.args[0][-2:], ['import:test', '--authorize-import=' + saved['sha256']])
        self.assertEqual(launch.call_args.kwargs['env']['TEST_UHH_FILE'], saved['path'])
        self.assertEqual(launch.call_args.kwargs['env']['DRY_RUN'], 'false')
        self.assertEqual(job['inputSha256'], saved['sha256'])

    def test_workflow_run_authorizes_only_the_selected_folder_input(self):
        source = self.root / 'folder-input.uhh'
        source.write_bytes(b'fixture')
        manager = RunManager(SimpleNamespace(logs=self.root / 'logs'))
        with patch('reviewer.pipeline.runner.prepare_pipeline'), patch('reviewer.pipeline.inputs.select_folder_input', return_value=source), patch('reviewer.instrument.validation.validate_file', return_value={'sha256': 'verified-folder-sha'}), patch('reviewer.ui_runs.subprocess.Popen') as launch, patch('reviewer.ui_runs.threading.Thread'):
            manager.start('workflow:run')
        self.assertEqual(launch.call_args.args[0][-2:], ['workflow:run', '--authorize-import=verified-folder-sha'])
        self.assertEqual(launch.call_args.kwargs['env']['DRY_RUN'], 'false')
        self.assertEqual(launch.call_args.kwargs['env']['TEST_UHH_FILE'], str(source))
