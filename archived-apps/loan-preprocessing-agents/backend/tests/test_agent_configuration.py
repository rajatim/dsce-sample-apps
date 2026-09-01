import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


class AgentConfigurationTest(unittest.TestCase):
    def test_explicit_service_instance_url_drives_wxo_api_base_url(self):
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHON_DOTENV_DISABLED": "1",
                "WXO_API_KEY": "test-wxo-key",
                "WXO_SERVICE_INSTANCE_URL": "https://wxo.example/instances/test-instance/",
            }
        )
        for variable in (
            "WXO_INSTANCE_ID",
            "WXO_INSTANCE_CLOUD",
            "WXO_INSTANCE_CLOUD_REGION",
        ):
            environment.pop(variable, None)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; "
                    "from utils.agents import WXO_API_KEY, base_url; "
                    "print(json.dumps({'api_key': WXO_API_KEY, 'base_url': base_url}))"
                ),
            ],
            cwd=BACKEND_DIRECTORY,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout.strip())
        self.assertEqual(config["api_key"], "test-wxo-key")
        self.assertEqual(
            config["base_url"],
            "https://wxo.example/instances/test-instance/v1/orchestrate",
        )


if __name__ == "__main__":
    unittest.main()
