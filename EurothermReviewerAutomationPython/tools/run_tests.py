"""Run regression tests with scratch files confined to the workspace drive."""
import sys
import tempfile
import unittest
from pathlib import Path

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
scratch = project.parent / '.test-temp'
scratch.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(scratch)
suite = unittest.defaultTestLoader.discover(str(project / 'tests'))
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
