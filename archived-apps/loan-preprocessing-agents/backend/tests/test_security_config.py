import os
from pathlib import Path
import subprocess
import sys
import unittest


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


class SecurityConfigTests(unittest.TestCase):
    def test_jwt_secret_key_comes_from_the_runtime_environment(self):
        environment = os.environ.copy()
        environment["JWT_SECRET_KEY"] = "runtime-only-test-key"

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import security; "
                    "print(security.SECRET_KEY == 'runtime-only-test-key')"
                ),
            ],
            cwd=BACKEND_DIRECTORY,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")


if __name__ == "__main__":
    unittest.main()
