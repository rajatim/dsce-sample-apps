import importlib.util
import unittest
from services.runtime_crypto import ConfigurationUnavailable
MODULE = importlib.util.find_spec('services.runtime_registry')
if MODULE:
    from services.runtime_registry import validate_groups, groups_from_environment

class RegistryTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(MODULE, 'settings registry exists')
    def test_unknown_keys_and_invalid_public_urls_rejected(self):
        valid = groups_from_environment('dsce', {'AUTH_PROVIDER': 'none', 'NEXTAUTH_SECRET': 's'*32, 'NEXTAUTH_URL':'https://dsce.example.test/dsce/api/auth', 'WIZARD_DATA_SOURCE':'local'})
        validate_groups('dsce',valid, allowed_hosts={'dsce.example.test'})
        valid['content']['LOAN_DEMO_URL'] = 'https://user:password@dsce.example.test/'
        with self.assertRaises(ConfigurationUnavailable): validate_groups('dsce',valid,allowed_hosts={'dsce.example.test'})
        valid['content']['LOAN_DEMO_URL'] = 'https://unapproved.example.test/'
        with self.assertRaises(ConfigurationUnavailable): validate_groups('dsce',valid,allowed_hosts={'dsce.example.test'})
        valid['content'].pop('LOAN_DEMO_URL')
        valid['auth']['NEW_UNREGISTERED_SECRET'] = 'hidden'
        with self.assertRaises(ConfigurationUnavailable): validate_groups('dsce',valid,allowed_hosts={'dsce.example.test'})
    def test_missing_conditional_provider_fields_rejected(self):
        valid = groups_from_environment('dsce', {'AUTH_PROVIDER': 'ivia', 'NEXTAUTH_SECRET': 's'*32, 'NEXTAUTH_URL':'https://dsce.example.test/dsce/api/auth', 'WIZARD_DATA_SOURCE':'local'})
        with self.assertRaises(ConfigurationUnavailable): validate_groups('dsce',valid,allowed_hosts={'dsce.example.test'})

if __name__ == '__main__': unittest.main()
