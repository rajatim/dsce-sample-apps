"""Loopback-only dev fixture: real status API/service, fake external transports.

Selected explicitly by scripts/dev.sh, never imported by the production app.
"""
from collections import Counter
import os
from types import SimpleNamespace
from typing import Literal

from fastapi import FastAPI

import main
from services.status_checks import check_cos, check_postgresql, check_watsonx, check_wxo
from services.system_status import SystemStatusService

COUNTS = Counter()
SCENARIO = 'auth_failure'


class DatabaseSession:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))

    def execute(self, statement):
        assert str(statement) == 'SELECT 1'
        COUNTS['postgresql'] += 1


class Bucket:
    def head_bucket(self, _):
        COUNTS['cos'] += 1


class Transport:
    def post(self, url, **_):
        if url.endswith('/icp4d-api/v1/authorize'):
            COUNTS['wxo_auth'] += 1
            if SCENARIO == 'auth_failure':
                return SimpleNamespace(status_code=401, json=lambda: {'message': 'Unauthorized'}, headers={})
            return SimpleNamespace(status_code=200, json=lambda: {'token': 'fixture-only'}, headers={})
        assert url == 'https://iam.cloud.ibm.com/identity/token'
        COUNTS['watsonx_auth'] += 1
        return SimpleNamespace(status_code=200, json=lambda: {'access_token': 'fixture-only'}, headers={})

    def get(self, url, **_):
        if url.endswith('/v1/orchestrate/agents'):
            COUNTS['wxo_metadata'] += 1
            if SCENARIO == 'metadata_failure':
                return SimpleNamespace(status_code=503, json=lambda: {'message': 'Service unavailable'}, headers={})
            return SimpleNamespace(status_code=200, json=lambda: [{'id': value} for value in ('processor', 'validator', 'decision')], headers={})
        assert url.endswith('/ml/v4/deployments')
        COUNTS['watsonx_metadata'] += 1
        return SimpleNamespace(status_code=200, json=lambda: {'resources': []}, headers={})


ENV = {
    'WXO_INSTANCE_CLOUD': 'cpd', 'WXO_SERVICE_INSTANCE_URL': 'https://fixture.invalid/instances/fixture',
    'WXO_CPD_USERNAME': 'fixture', 'WXO_API_KEY': 'fixture',
    'DOC_PROCESSOR_AGENT_ID': 'processor', 'DOCUMENT_VALIDATION_AGENT_ID': 'validator',
    'FINAL_DECISION_AGENT_ID': 'decision', 'WATSONX_APIKEY': 'fixture',
    'WATSONX_PROJECT_ID': 'fixture', 'WATSONX_URL': 'https://fixture.invalid',
}
def environment():
    return main.get_settings().values if os.getenv('RUNTIME_CONFIG_MODE') == 'database' else ENV


def reset_checks():
    main.system_status_service.close()
    main.system_status_service = SystemStatusService(dependency_checks={
        'postgresql': lambda now: check_postgresql(DatabaseSession, now),
        'cos': lambda now: check_cos(Bucket, 'fixture', now),
        'watsonx_ai': lambda now: check_watsonx(environment(), Transport(), now),
        'wxo': lambda now: check_wxo(environment(), Transport(), now),
    })


reset_checks()
app = FastAPI(title='Local status verification fixtures')
app.get('/system-status')(main.system_status)
app.get('/healthz')(main.healthcheck)
app.get('/readyz')(main.readiness)


@app.post('/token')
def fixture_session():
    return {'access_token': 'local-fixture-only', 'token_type': 'bearer'}


@app.get('/__test/check-counts')
def check_counts():
    return dict(COUNTS)


@app.post('/__test/wxo-scenario/{scenario}')
def set_wxo_scenario(scenario: Literal['ready', 'auth_failure', 'metadata_failure']):
    global SCENARIO
    SCENARIO = scenario
    reset_checks()
    return {'scenario': SCENARIO}
