import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
MODULE=importlib.util.find_spec('scripts.runtime_settings')
if MODULE:
    from scripts.runtime_settings import read_protected_json, candidate_groups

class OperatorTests(unittest.TestCase):
    def test_rejects_world_readable_secret_input(self):
        self.assertIsNotNone(MODULE,'protected operator CLI exists')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.json';path.write_text('{"secret":"test-only"}');path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError,'Protected input required'): read_protected_json(path)
            path.chmod(0o600)
            self.assertEqual(read_protected_json(path),{'secret':'test-only'})
    def test_import_does_not_overwrite_existing_active_revisions(self):
        self.assertIsNotNone(MODULE,'protected operator CLI exists')
        with self.assertRaisesRegex(RuntimeError,'already initialized'):
            candidate_groups('import','dsce',{'NEXTAUTH_SECRET':'new'},{'auth':'active'})

if __name__ == '__main__': unittest.main()
