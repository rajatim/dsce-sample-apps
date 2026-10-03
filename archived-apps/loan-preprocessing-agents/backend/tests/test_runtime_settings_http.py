import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from services.runtime_crypto import ConfigurationUnavailable

class HttpSettingsTests(unittest.TestCase):
    def test_config_outage_fails_dependent_requests_but_liveness_survives(self):
        with patch.dict('os.environ',{'RUNTIME_CONFIG_MODE':'database'}), patch('services.runtime_settings.get_settings',side_effect=ConfigurationUnavailable()):
            client=TestClient(main.app)
            self.assertEqual(client.get('/healthz').status_code,200)
            response=client.get('/users/me')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json(),{'detail':'Configuration unavailable'})

if __name__ == '__main__': unittest.main()
