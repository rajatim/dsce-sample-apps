"""Exercise launcher guards without starting application services."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/dev.sh'


class LauncherTests(unittest.TestCase):
    def run_check(self, content):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / '.env'
            env_file.write_text(content)
            return subprocess.run(['bash', str(SCRIPT), '--check'], env={**os.environ, 'LOAN_ENV_FILE': str(env_file)}, capture_output=True, text=True)

    def test_rejects_framework_default_before_starting(self):
        r = self.run_check('SERVER_PORT=8000\nVITE_PORT=5316\nDATABASE_URL=sqlite:///:memory:\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Default port is not allowed', r.stderr)

    def test_rejects_missing_port(self):
        r = self.run_check('SERVER_PORT=\nVITE_PORT=5316\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Invalid SERVER_PORT', r.stderr)

    def test_rejects_occupied_port_without_stopping_listener(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            r = self.run_check(f'SERVER_PORT={port}\nVITE_PORT=5316\nDATABASE_URL=sqlite:///:memory:\n')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('no process was stopped', r.stderr)
            self.assertNotEqual(listener.fileno(), -1)
