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

    def test_auth_url_must_match_runtime_auth_path(self):
        groups = groups_from_environment('dsce', {'NEXTAUTH_SECRET':'s'*32, 'NEXTAUTH_URL':'https://dsce.example.test/dsce/api/auth'})
        for url in ('https://dsce.example.test/', 'https://dsce.example.test/dsce/api/auth/', 'https://dsce.example.test/dsce/api/auth?x=1'):
            groups['auth']['NEXTAUTH_URL'] = url
            with self.subTest(url=url), self.assertRaises(ConfigurationUnavailable):
                validate_groups('dsce', groups, allowed_hosts={'dsce.example.test'})

    def test_derived_wxo_url_requires_safe_components_and_approved_host(self):
        values = {key: 'fixture' for fields in __import__('services.runtime_registry', fromlist=['REGISTRY']).REGISTRY['applications']['loan'].values() for key in fields}
        values.update(JWT_SECRET_KEY='s'*32, WXO_INSTANCE_CLOUD='ibmcloud', WXO_INSTANCE_CLOUD_REGION='us-south', WXO_INSTANCE_ID='instance-1', WXO_SERVICE_INSTANCE_URL='', WATSONX_URL='https://provider.example.test', COS_ENDPOINT='https://provider.example.test')
        groups = groups_from_environment('loan', values)
        hosts = {'provider.example.test','api.us-south.watson-orchestrate.cloud.ibm.com'}
        validate_groups('loan', groups, allowed_hosts=hosts)
        for field, value in [('WXO_INSTANCE_CLOUD_REGION','unapproved.example/'), ('WXO_INSTANCE_CLOUD_REGION','eu-de'), ('WXO_INSTANCE_ID','../other?x=1')]:
            invalid = {name: dict(fields) for name, fields in groups.items()}
            invalid['wxo'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ConfigurationUnavailable):
                validate_groups('loan', invalid, allowed_hosts=hosts)

if __name__ == '__main__': unittest.main()
