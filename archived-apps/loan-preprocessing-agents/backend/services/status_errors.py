"""Public diagnostics: preserve received evidence without publishing raw bodies."""
from collections.abc import Mapping
import re

import requests

from status_models import StatusProblem
from services.runtime_crypto import ConfigurationUnavailable

# Exact reviewed provider vocabulary. Arbitrary text is never safe by default.
_PROVIDER_CODES = frozenset({
    'token_quota_reached', 'too_many_requests', 'rate_limit_exceeded',
    'unauthorized', 'forbidden', 'invalid_api_key', 'invalid_token',
    'access_denied', 'not_found', 'service_unavailable', 'internal_server_error',
    'AccessDenied', 'NoSuchBucket', 'InvalidAccessKeyId', 'SignatureDoesNotMatch',
    'ExpiredToken', 'SlowDown', 'RequestTimeout',
})
_PROVIDER_MESSAGES = frozenset({
    'Unauthorized', 'Forbidden', 'Access Denied', 'Access denied',
    'Too many requests', 'Service unavailable', 'Internal server error',
    'Invalid API key', 'Invalid token', 'Token quota reached',
})
_UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')


def problem_for(*, service, stage, code, http_status=None, **fields):
    category = {
        'http_error': 'provider', 'invalid_response': 'response',
        'missing_configuration': 'configuration', 'agent_not_registered': 'registration',
        'timeout': 'timeout', 'connection_error': 'connection', 'tls_error': 'connection',
        'check_failed': 'unknown',
    }[code]
    retryable = code in {'timeout', 'connection_error'} or (
        http_status is not None and (http_status == 429 or http_status >= 500)
    )
    if fields.get('provider_code') == 'token_quota_reached':
        retryable = False
        category = 'quota'
    elif http_status in (401, 403):
        category = 'authorization'
    return StatusProblem(
        service=service, stage=stage, code=code, category=category,
        http_status=http_status, retryable_now=retryable,
        action='retry_later' if retryable else 'review_configuration', **fields,
    )


def problem_from_http(*, service, stage, status_code, payload, headers):
    body = payload if isinstance(payload, Mapping) else {}
    errors = body.get('errors')
    candidate = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], Mapping) else body
    code = candidate.get('code')
    message = candidate.get('message')
    trace = body.get('trace')
    if not isinstance(trace, str) or not _UUID.fullmatch(trace):
        trace = next((value for key, value in headers.items()
                      if key.lower() in {'x-request-id', 'x-global-transaction-id'}
                      and isinstance(value, str) and _UUID.fullmatch(value)), None)
    return problem_for(
        service=service, stage=stage, code='http_error', http_status=status_code,
        provider_code=code if isinstance(code, str) and code in _PROVIDER_CODES else None,
        provider_message=message if isinstance(message, str) and message in _PROVIDER_MESSAGES else None,
        trace_id=trace,
    )


def problem_from_exception(*, service, stage, error):
    if isinstance(error, ConfigurationUnavailable):
        return problem_for(service=service, stage="configuration", code="missing_configuration")
    # Typed adapters may already carry a sanitized problem from an HTTP response.
    if isinstance(getattr(error, 'problem', None), StatusProblem):
        return error.problem
    response = getattr(error, 'response', None)
    if isinstance(response, Mapping):  # COS ClientError
        metadata = response.get('ResponseMetadata', {})
        status = metadata.get('HTTPStatusCode') if isinstance(metadata, Mapping) else None
        if isinstance(status, int) and 100 <= status <= 599:
            error_body = response.get('Error', {})
            payload = {'code': error_body.get('Code'), 'message': error_body.get('Message')} if isinstance(error_body, Mapping) else {}
            return problem_from_http(service=service, stage=stage, status_code=status, payload=payload, headers={})
    if isinstance(error, (requests.Timeout, TimeoutError)):
        code = 'timeout'
    elif isinstance(error, requests.exceptions.SSLError):
        code = 'tls_error'
    elif isinstance(error, (requests.ConnectionError, ConnectionError)):
        code = 'connection_error'
    else:
        code = 'check_failed'
    return problem_for(service=service, stage=stage, code=code)
