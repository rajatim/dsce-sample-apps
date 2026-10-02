import unittest
from services.status_errors import problem_from_http, problem_from_exception


class PublicProblemTests(unittest.TestCase):
    def test_unrecognized_or_private_fields_never_escape(self):
        for body in ({'code': 'private-token', 'message': '<script>private</script>', 'trace': 'private-token'},
                     {'errors': [{'code': ['private'], 'message': 'private' * 1000}]},
                     ['private'], 'private'):
            with self.subTest(body_type=type(body).__name__):
                result = problem_from_http(service='wxo', stage='authentication', status_code=403,
                    payload=body, headers={'Authorization': 'private', 'x-request-id': 'private'})
                self.assertEqual(result.http_status, 403)
                self.assertIsNone(result.provider_code)
                self.assertIsNone(result.provider_message)
                self.assertIsNone(result.trace_id)
                self.assertNotIn('private', result.model_dump_json())

    def test_quota_rejection_is_received_evidence_not_a_retry_claim(self):
        result = problem_from_http(service='watsonx_ai', stage='metadata', status_code=403,
            payload={'errors': [{'code': 'token_quota_reached', 'message': 'Token quota reached'}]}, headers={})
        self.assertEqual(result.provider_code, 'token_quota_reached')
        self.assertEqual(result.provider_message, 'Token quota reached')
        self.assertEqual(result.category, 'quota')
        self.assertFalse(result.retryable_now)

    def test_cos_error_has_received_status_and_code_without_bucket_name(self):
        error = RuntimeError('private-bucket')
        error.response = {'ResponseMetadata': {'HTTPStatusCode': 403}, 'Error': {'Code': 'AccessDenied', 'Message': 'private-bucket'}}
        result = problem_from_exception(service='cos', stage='metadata', error=error)
        self.assertEqual(result.http_status, 403)
        self.assertEqual(result.provider_code, 'AccessDenied')
        self.assertIsNone(result.provider_message)
