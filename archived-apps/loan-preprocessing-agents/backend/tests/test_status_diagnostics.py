"""Provider failures must survive status checks without exposing private bodies."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from services.status_checks import check_wxo, check_watsonx, check_cos, check_postgresql

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
CPD = {
    'WXO_API_KEY': 'private-key', 'WXO_INSTANCE_CLOUD': 'cpd',
    'WXO_SERVICE_INSTANCE_URL': 'https://cpd.example/instances/private-instance',
    'WXO_CPD_USERNAME': 'private-user', 'DOC_PROCESSOR_AGENT_ID': 'processor',
    'DOCUMENT_VALIDATION_AGENT_ID': 'validator', 'FINAL_DECISION_AGENT_ID': 'decision',
}


def response(status, payload, headers=None):
    return SimpleNamespace(status_code=status, json=lambda: payload, headers=headers or {})


class StatusDiagnosticTests(unittest.TestCase):
    def test_cpd_auth_failure_retains_received_status_and_shared_cause(self):
        http = Mock()
        http.post.return_value = response(401, {'message': 'Unauthorized'})
        rows = check_wxo(CPD, http, NOW)
        self.assertIsNotNone(getattr(rows[0], 'problem', None))
        self.assertEqual(rows[0].problem.http_status, 401)
        self.assertEqual(rows[0].problem.stage, 'authentication')
        self.assertEqual(rows[0].problem.provider_message, 'Unauthorized')
        self.assertIsNone(rows[0].problem.provider_code)
        for row in rows[1:]:
            self.assertEqual(row.problem.blocked_by, 'wxo')
            self.assertEqual(row.evidence.value, 'not_verified')
        http.get.assert_not_called()

    def test_metadata_error_preserves_code_but_omits_private_message(self):
        http = Mock()
        http.post.return_value = response(200, {'token': 'private-token'})
        http.get.return_value = response(429, {'errors': [{
            'code': 'too_many_requests', 'message': 'private-key private-user https://private.example',
        }], 'trace': 'd0e6a7a1-e502-4cd7-a845-e163d3c45302'})
        row = check_wxo(CPD, http, NOW)[0]
        self.assertIsNotNone(getattr(row, 'problem', None))
        self.assertEqual(row.problem.stage, 'metadata')
        self.assertEqual(row.problem.http_status, 429)
        self.assertEqual(row.problem.provider_code, 'too_many_requests')
        self.assertIsNone(row.problem.provider_message)
        self.assertEqual(row.problem.trace_id, 'd0e6a7a1-e502-4cd7-a845-e163d3c45302')
        for secret in ('private-key', 'private-user', 'private-token', 'https://private'):
            self.assertNotIn(secret, row.model_dump_json())

    def test_bad_success_schema_keeps_200_and_parsing_stage(self):
        http = Mock()
        http.post.return_value = response(200, {'token': 'private-token'})
        http.get.return_value = response(200, {'unexpected': 'private-value'})
        row = check_wxo(CPD, http, NOW)[0]
        self.assertIsNotNone(getattr(row, 'problem', None))
        self.assertEqual(row.problem.http_status, 200)
        self.assertEqual(row.problem.stage, 'response_parsing')
        self.assertEqual(row.problem.code, 'invalid_response')

    def test_missing_agent_is_not_a_wxo_outage(self):
        http = Mock()
        http.post.return_value = response(200, {'token': 'private-token'})
        http.get.return_value = response(200, [{'id': 'processor'}, {'id': 'decision'}])
        rows = check_wxo(CPD, http, NOW)
        self.assertEqual(rows[0].status.value, 'ready')
        self.assertIsNotNone(getattr(rows[2], 'problem', None))
        self.assertEqual(rows[2].problem.code, 'agent_not_registered')
        self.assertIsNone(rows[2].problem.blocked_by)

    def test_transport_failures_have_stage_without_invented_http_status(self):
        for error, code in [(requests.Timeout('private-token'), 'timeout'),
                            (requests.exceptions.SSLError('private-host'), 'tls_error'),
                            (requests.ConnectionError('private-host'), 'connection_error')]:
            with self.subTest(code=code):
                http = Mock()
                http.post.side_effect = error
                row = check_wxo(CPD, http, NOW)[0]
                self.assertIsNotNone(getattr(row, 'problem', None))
                self.assertEqual(row.problem.code, code)
                self.assertEqual(row.problem.stage, 'authentication')
                self.assertIsNone(row.problem.http_status)
                self.assertNotIn('private-', row.model_dump_json())

    def test_watsonx_auth_and_metadata_failures_are_distinct(self):
        env = {'WATSONX_APIKEY': 'private', 'WATSONX_PROJECT_ID': 'private', 'WATSONX_URL': 'https://example.test'}
        for auth_status, metadata_status, stage in [(403, 200, 'authentication'), (200, 503, 'metadata')]:
            with self.subTest(stage=stage):
                http = Mock()
                http.post.return_value = response(auth_status, {'access_token': 'private'})
                http.get.return_value = response(metadata_status, {})
                row = check_watsonx(env, http, NOW)
                self.assertIsNotNone(getattr(row, 'problem', None))
                self.assertEqual(row.problem.stage, stage)
                self.assertEqual(row.problem.http_status, auth_status if stage == 'authentication' else metadata_status)

    def test_database_and_cos_exceptions_return_safe_diagnostics(self):
        factory = Mock(side_effect=RuntimeError('password=private applicant=private'))
        for row in (check_postgresql(factory, NOW), check_cos(factory, 'private-bucket', NOW)):
            self.assertIsNotNone(getattr(row, 'problem', None))
            self.assertNotIn('private', row.model_dump_json())
            self.assertIsNone(row.problem.http_status)

    def test_missing_configuration_is_explained_without_values(self):
        row = check_wxo({}, Mock(), NOW)[0]
        self.assertIsNotNone(getattr(row, 'problem', None))
        self.assertEqual(row.problem.code, 'missing_configuration')
        self.assertEqual(row.problem.stage, 'configuration')

if __name__ == '__main__':
    unittest.main()
