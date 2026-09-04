import os
import subprocess
import sys
import time
import unittest
import json
import tempfile
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
IBM_SERVICE_VARIABLES = (
    "WATSONX_APIKEY",
    "WATSONX_PROJECT_ID",
    "WATSONX_URL",
    "COS_ENDPOINT",
    "COS_API_KEY_ID",
    "COS_INSTANCE_CRN",
    "WXO_API_KEY",
    "WXO_INSTANCE_ID",
    "DOC_PROCESSOR_AGENT_ID",
    "DOCUMENT_VALIDATION_AGENT_ID",
    "FINAL_DECISION_AGENT_ID",
)


class StartupTest(unittest.TestCase):
    def test_api_imports_without_ibm_service_credentials(self):
        environment = os.environ.copy()
        for variable in IBM_SERVICE_VARIABLES:
            environment.pop(variable, None)

        result = subprocess.run(
            [sys.executable, "-c", "import main; print(main.app.title)"],
            cwd=BACKEND_DIRECTORY,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Loan Application API")

    def test_health_endpoint_is_available_without_authentication(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from fastapi.testclient import TestClient\n"
                    "import main\n"
                    "def fail(*args, **kwargs):\n"
                    "    raise RuntimeError('dependency failed')\n"
                    "main.check_postgresql = fail\n"
                    "main.check_cos = fail\n"
                    "main.check_watsonx = fail\n"
                    "main.check_wxo = fail\n"
                    "main.check_openllmetry = fail\n"
                    "main.get_recent_agent_activity = fail\n"
                    "response = TestClient(main.app).get('/healthz')\n"
                    "print(response.status_code)\n"
                    "print(response.text)"
                ),
            ],
            cwd=BACKEND_DIRECTORY,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        status_code, body = result.stdout.strip().splitlines()
        self.assertEqual(status_code, "200")
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_upload_directory_can_be_configured_for_a_persistent_volume(self):
        with tempfile.TemporaryDirectory() as upload_directory:
            environment = os.environ.copy()
            environment["UPLOAD_DIRECTORY"] = upload_directory
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import main; print(main.UPLOAD_DIRECTORY)",
                ],
                cwd=BACKEND_DIRECTORY,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), upload_directory)

    def test_direct_entrypoint_serves_openapi_on_documented_port(self):
        environment = os.environ.copy()
        for variable in IBM_SERVICE_VARIABLES:
            environment.pop(variable, None)

        process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=BACKEND_DIRECTORY,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(f"Backend exited before becoming ready:\n{stdout}\n{stderr}")

                try:
                    with urlopen("http://127.0.0.1:8000/openapi.json", timeout=0.25) as response:
                        self.assertEqual(response.status, 200)
                        return
                except URLError:
                    time.sleep(0.1)

            self.fail("Backend did not serve OpenAPI on documented port 8000")
        finally:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
