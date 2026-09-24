import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils import agents


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


class AgentConfigurationTest(unittest.TestCase):
    def test_cpd_api_key_is_exchanged_for_a_bearer_token(self):
        response = SimpleNamespace(
            status_code=200, json=lambda: {"token": "cpd-bearer-token"}
        )
        with (
            patch.object(agents, "WXO_INSTANCE_CLOUD", "cpd"),
            patch.object(agents, "WXO_CPD_USERNAME", "kubeadmin", create=True),
            patch.object(
                agents,
                "WXO_SERVICE_INSTANCE_URL",
                "https://cpd.example/orchestrate/cpd-instance/instances/123",
            ),
            patch.object(agents.requests, "post", return_value=response) as post,
        ):
            token = agents.get_bearer_token("test-api-key")

        self.assertEqual(token, "cpd-bearer-token")
        post.assert_called_once_with(
            "https://cpd.example/icp4d-api/v1/authorize",
            headers={"Content-Type": "application/json"},
            json={"username": "kubeadmin", "api_key": "test-api-key"},
            timeout=(10, 20),
        )

    def test_cpd_rejected_token_does_not_expose_key_or_response(self):
        response = SimpleNamespace(
            status_code=401, json=lambda: {"message": "test-api-key denied"}
        )
        with (
            patch.object(agents, "WXO_INSTANCE_CLOUD", "cpd"),
            patch.object(agents, "WXO_CPD_USERNAME", "kubeadmin", create=True),
            patch.object(
                agents,
                "WXO_SERVICE_INSTANCE_URL",
                "https://cpd.example/orchestrate/cpd-instance/instances/123",
            ),
            patch.object(agents.requests, "post", return_value=response),
        ):
            with self.assertRaises(RuntimeError) as captured:
                agents.get_bearer_token("test-api-key")

        self.assertIn("CPD authentication failed", str(captured.exception))
        self.assertNotIn("test-api-key", str(captured.exception))

    def test_cpd_empty_token_is_rejected(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"token": ""})
        with (
            patch.object(agents, "WXO_INSTANCE_CLOUD", "cpd"),
            patch.object(agents, "WXO_CPD_USERNAME", "kubeadmin", create=True),
            patch.object(
                agents,
                "WXO_SERVICE_INSTANCE_URL",
                "https://cpd.example/orchestrate/cpd-instance/instances/123",
            ),
            patch.object(agents.requests, "post", return_value=response),
        ):
            with self.assertRaisesRegex(RuntimeError, "CPD authentication failed"):
                agents.get_bearer_token("test-api-key")

    def test_cpd_malformed_token_payload_is_rejected_without_details(self):
        response = SimpleNamespace(status_code=200, json=lambda: ["test-api-key"])
        with (
            patch.object(agents, "WXO_INSTANCE_CLOUD", "cpd"),
            patch.object(agents, "WXO_CPD_USERNAME", "kubeadmin", create=True),
            patch.object(
                agents,
                "WXO_SERVICE_INSTANCE_URL",
                "https://cpd.example/orchestrate/cpd-instance/instances/123",
            ),
            patch.object(agents.requests, "post", return_value=response),
        ):
            with self.assertRaises(RuntimeError) as captured:
                agents.get_bearer_token("test-api-key")

        self.assertEqual(str(captured.exception), "CPD authentication failed")

    def test_unknown_wxo_provider_is_rejected(self):
        with patch.object(agents, "WXO_INSTANCE_CLOUD", "unknown-provider"):
            with self.assertRaisesRegex(ValueError, "Unsupported WXO provider"):
                agents.get_bearer_token("test-api-key")

    def test_cpd_service_instance_url_drives_agent_api_path(self):
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHON_DOTENV_DISABLED": "1",
                "WXO_INSTANCE_CLOUD": "cpd",
                "WXO_CPD_USERNAME": "kubeadmin",
                "WXO_SERVICE_INSTANCE_URL": (
                    "https://cpd.example/orchestrate/cpd-instance/instances/123"
                ),
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", "from utils.agents import base_url; print(base_url)"],
            cwd=BACKEND_DIRECTORY,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "https://cpd.example/orchestrate/cpd-instance/instances/123/v1/orchestrate",
        )

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
