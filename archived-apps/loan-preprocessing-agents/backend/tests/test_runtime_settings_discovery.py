import ssl
import unittest
from unittest.mock import patch, Mock
from scripts import runtime_settings
from services.runtime_registry import groups_from_environment


class DiscoveryTransportTests(unittest.TestCase):
    def test_discovery_session_preserves_certificate_and_hostname_verification(self):
        self.assertTrue(hasattr(runtime_settings, 'build_discovery_session'))
        with runtime_settings.build_discovery_session() as session:
            context = session.get_adapter('https://').poolmanager.connection_pool_kw['ssl_context']
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertTrue(context.hostname_checks_common_name)

    def test_provider_validation_uses_verified_session_without_redirects(self):
        values = dict(AUTH_PROVIDER='ivia', IVIA_WELL_KNOWN='https://id.example.test/metadata', IVIA_ISSUER='https://id.example.test', WIZARD_DATA_SOURCE='local')
        groups = groups_from_environment('dsce', values)
        response = Mock(status_code=200)
        response.json.return_value = dict(issuer=values['IVIA_ISSUER'], authorization_endpoint='https://id.example.test/auth', token_endpoint='https://id.example.test/token', jwks_uri='https://id.example.test/keys')
        session = Mock()
        session.get.return_value = response
        with patch.object(runtime_settings, 'build_discovery_session', create=True) as factory:
            factory.return_value.__enter__.return_value = session
            runtime_settings.validate_providers('dsce', groups, {'id.example.test'})
            session.get.assert_called_once_with(values['IVIA_WELL_KNOWN'], timeout=(3, 5), allow_redirects=False)


if __name__ == '__main__': unittest.main()
