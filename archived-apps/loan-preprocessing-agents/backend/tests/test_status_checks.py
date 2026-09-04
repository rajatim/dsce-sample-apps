import unittest
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from status_models import EvidenceKind, StatusValue
from services import status_checks
from services.status_checks import check_cos, check_openllmetry, check_postgresql, check_watsonx, check_wxo
from utils.cos_client import COSClient


CHECKED_AT = datetime(2026, 9, 4, 8, 30, tzinfo=timezone.utc)
IAM_URL = "https://iam.cloud.ibm.com/identity/token"
AWS_IAM_URL = "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token"
IAM_DATA = {
    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
    "apikey": "test-api-key",
}
AGENT_IDS = ("processor-id", "validator-id", "decision-id")


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class UnexpectedHttpRequest(BaseException):
    """Escape production's request-error handling so contract mistakes fail directly."""


class StrictHttp:
    """Allow only the exact read-only status-check requests configured by a test."""

    def __init__(self, expected_requests):
        self.expected_requests = list(expected_requests)
        self.requests = []

    def _request(self, method, url, **kwargs):
        actual = (method, url, kwargs)
        if not self.expected_requests:
            raise UnexpectedHttpRequest(f"Unexpected HTTP request: {actual!r}")
        expected_method, expected_url, expected_kwargs, outcome = self.expected_requests.pop(0)
        expected = (expected_method, expected_url, expected_kwargs)
        if actual != expected:
            raise UnexpectedHttpRequest(f"Expected {expected!r}, got {actual!r}")
        self.requests.append(actual)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def assert_exhausted(self):
        if self.expected_requests:
            raise UnexpectedHttpRequest(
                f"Expected requests were not made: {self.expected_requests!r}"
            )


def token_request(api_key="test-api-key", outcome=None):
    return (
        "POST",
        IAM_URL,
        {
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "data": {**IAM_DATA, "apikey": api_key},
            "timeout": (2, 3),
        },
        outcome or FakeResponse(200, {"access_token": "private-token"}),
    )


class StrictSession:
    def __init__(self, outcome=None, dialect_name="postgresql"):
        self.outcome = outcome
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.statements = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True

    def execute(self, statement):
        sql = str(statement)
        if sql != "SELECT 1":
            raise AssertionError(f"Only SELECT 1 is allowed, got {sql!r}")
        self.statements.append(sql)
        if self.outcome is not None:
            raise self.outcome

    def get_bind(self):
        return self.bind


class StrictCOSSDK:
    """The fake deliberately exposes no upload, list, delete, or mutation API."""

    def __init__(self, outcome=None):
        self.outcome = outcome
        self.checked_buckets = []

    def head_bucket(self, *, Bucket):
        self.checked_buckets.append(Bucket)
        if self.outcome is not None:
            raise self.outcome


def cos_client_with(sdk):
    client = object.__new__(COSClient)
    client._cos = sdk
    return client


class DependencyCheckTests(unittest.TestCase):
    def test_status_postgresql_factory_has_dedicated_connection_and_query_deadlines(self):
        engine = object()
        factory = object()
        with (
            patch.object(status_checks, "create_engine", return_value=engine) as create,
            patch.object(status_checks, "sessionmaker", return_value=factory) as sessions,
        ):
            result = status_checks.build_status_session_factory(
                "postgresql+psycopg://status-user:status-password@127.0.0.1/status-db"
            )

        self.assertIs(result, factory)
        create.assert_called_once_with(
            "postgresql+psycopg://status-user:status-password@127.0.0.1/status-db",
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 1,
                "options": "-c statement_timeout=2000",
            },
        )
        sessions.assert_called_once_with(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )

    def test_status_http_client_disables_transport_retries(self):
        http = status_checks.build_status_http_client()
        self.addCleanup(http.close)

        self.assertEqual(http.adapters["https://"].max_retries.total, 0)
        self.assertEqual(http.adapters["http://"].max_retries.total, 0)

    def test_sqlite_fallback_is_not_a_verified_postgresql_dependency(self):
        engine = create_engine("sqlite://")
        statements = []
        event.listen(
            engine,
            "before_cursor_execute",
            lambda connection, cursor, statement, parameters, context, executemany:
                statements.append(statement),
        )
        sqlite_session_factory = sessionmaker(bind=engine)
        self.addCleanup(engine.dispose)

        result = check_postgresql(sqlite_session_factory, CHECKED_AT)

        self.assertIs(result.status, StatusValue.NOT_CONFIGURED)
        self.assertIs(result.evidence, EvidenceKind.NOT_VERIFIED)
        self.assertEqual(result.message, "PostgreSQL is not configured.")
        self.assertEqual(statements, [])

    def test_postgresql_executes_only_select_one_and_reports_ready(self):
        session = StrictSession()

        result = check_postgresql(lambda: session, CHECKED_AT)

        self.assertEqual(result.id, "postgresql")
        self.assertIs(result.status, StatusValue.READY)
        self.assertIs(result.evidence, EvidenceKind.LIVE_CHECK)
        self.assertEqual(result.message, "PostgreSQL is reachable.")
        self.assertEqual(result.checked_at, CHECKED_AT)
        self.assertEqual(session.statements, ["SELECT 1"])
        self.assertTrue(session.closed)

    def test_postgresql_failure_uses_fixed_public_copy(self):
        session = StrictSession(RuntimeError("postgres password leaked"))

        with self.assertLogs("services.status_checks", level="WARNING") as captured:
            result = check_postgresql(lambda: session, CHECKED_AT)

        self.assertIs(result.status, StatusValue.UNAVAILABLE)
        self.assertIs(result.evidence, EvidenceKind.LIVE_CHECK)
        self.assertEqual(result.message, "PostgreSQL is unavailable.")
        self.assertNotIn("password", result.model_dump_json())
        self.assertEqual(
            captured.output,
            [
                "WARNING:services.status_checks:"
                "PostgreSQL status check failed (RuntimeError)"
            ],
        )

    def test_cos_calls_only_head_bucket_and_reports_ready(self):
        sdk = StrictCOSSDK()

        result = check_cos(lambda: cos_client_with(sdk), "loan-demo", CHECKED_AT)

        self.assertEqual(result.id, "cos")
        self.assertIs(result.status, StatusValue.READY)
        self.assertIs(result.evidence, EvidenceKind.LIVE_CHECK)
        self.assertEqual(result.message, "Cloud Object Storage is reachable.")
        self.assertEqual(sdk.checked_buckets, ["loan-demo"])

    def test_cos_missing_bucket_is_not_configured_without_creating_client(self):
        def forbidden_factory():
            raise AssertionError("client factory must not be called")

        result = check_cos(forbidden_factory, "", CHECKED_AT)

        self.assertIs(result.status, StatusValue.NOT_CONFIGURED)
        self.assertIs(result.evidence, EvidenceKind.NOT_VERIFIED)
        self.assertEqual(result.message, "Cloud Object Storage is not configured.")

    def test_cos_failure_uses_fixed_public_copy(self):
        sdk = StrictCOSSDK(RuntimeError("provider body must stay private"))

        with self.assertLogs("services.status_checks", level="WARNING") as captured:
            result = check_cos(
                lambda: cos_client_with(sdk), "loan-demo", CHECKED_AT
            )

        self.assertIs(result.status, StatusValue.UNAVAILABLE)
        self.assertIs(result.evidence, EvidenceKind.LIVE_CHECK)
        self.assertEqual(result.message, "Cloud Object Storage is unavailable.")
        self.assertNotIn("provider body", result.model_dump_json())
        self.assertEqual(
            captured.output,
            [
                "WARNING:services.status_checks:"
                "Cloud Object Storage status check failed (RuntimeError)"
            ],
        )

    def test_watsonx_missing_variables_are_not_configured_without_http(self):
        http = StrictHttp([])

        result = check_watsonx({}, http, CHECKED_AT)

        self.assertIs(result.status, StatusValue.NOT_CONFIGURED)
        self.assertIs(result.evidence, EvidenceKind.NOT_VERIFIED)
        self.assertEqual(result.message, "watsonx.ai is not configured.")
        http.assert_exhausted()

    def test_watsonx_gets_iam_token_then_reads_project_metadata(self):
        environment = {
            "WATSONX_APIKEY": "test-api-key",
            "WATSONX_PROJECT_ID": "project-id",
            "WATSONX_URL": "https://watsonx.example/",
        }
        http = StrictHttp(
            [
                token_request(),
                (
                    "GET",
                    "https://watsonx.example/v2/projects/project-id",
                    {
                        "headers": {"Authorization": "Bearer private-token"},
                        "timeout": (2, 3),
                    },
                    FakeResponse(200, {"name": "loan-project"}),
                ),
            ]
        )

        result = check_watsonx(environment, http, CHECKED_AT)

        self.assertIs(result.status, StatusValue.READY)
        self.assertIs(result.evidence, EvidenceKind.LIVE_CHECK)
        self.assertEqual(result.message, "watsonx.ai is reachable.")
        self.assertNotIn("private-token", result.model_dump_json())
        http.assert_exhausted()

    def test_watsonx_http_failures_use_the_same_safe_status(self):
        environment = {
            "WATSONX_APIKEY": "test-api-key",
            "WATSONX_PROJECT_ID": "project-id",
            "WATSONX_URL": "https://watsonx.example",
        }
        for status_code in (401, 403, 404, 429, 500, 503):
            with self.subTest(status_code=status_code):
                http = StrictHttp(
                    [
                        token_request(),
                        (
                            "GET",
                            "https://watsonx.example/v2/projects/project-id",
                            {
                                "headers": {"Authorization": "Bearer private-token"},
                                "timeout": (2, 3),
                            },
                            FakeResponse(status_code, {"error": "provider secret"}),
                        ),
                    ]
                )

                with self.assertLogs(
                    "services.status_checks", level="WARNING"
                ) as captured:
                    result = check_watsonx(environment, http, CHECKED_AT)

                self.assertIs(result.status, StatusValue.UNAVAILABLE)
                self.assertIs(result.evidence, EvidenceKind.LIVE_CHECK)
                self.assertEqual(result.message, "watsonx.ai is unavailable.")
                self.assertNotIn("provider secret", result.model_dump_json())
                self.assertEqual(
                    captured.output,
                    [
                        "WARNING:services.status_checks:"
                        "watsonx.ai status check failed (_HTTPStatusFailure)"
                    ],
                )
                http.assert_exhausted()

    def test_watsonx_timeout_uses_fixed_public_copy(self):
        environment = {
            "WATSONX_APIKEY": "test-api-key",
            "WATSONX_PROJECT_ID": "project-id",
            "WATSONX_URL": "https://watsonx.example",
        }
        http = StrictHttp([token_request(outcome=TimeoutError("private timeout detail"))])

        with self.assertLogs("services.status_checks", level="WARNING") as captured:
            result = check_watsonx(environment, http, CHECKED_AT)

        self.assertIs(result.status, StatusValue.UNAVAILABLE)
        self.assertEqual(result.message, "watsonx.ai is unavailable.")
        self.assertNotIn("private timeout detail", result.model_dump_json())
        self.assertEqual(
            captured.output,
            [
                "WARNING:services.status_checks:"
                "watsonx.ai status check failed (TimeoutError)"
            ],
        )
        http.assert_exhausted()

    def test_wxo_missing_variables_return_four_not_configured_results(self):
        http = StrictHttp([])

        results = check_wxo({}, http, CHECKED_AT)

        self.assertEqual(
            [item.id for item in results],
            [
                "wxo",
                "document_processing_agent",
                "document_validation_agent",
                "final_decision_agent",
            ],
        )
        self.assertTrue(
            all(item.status is StatusValue.NOT_CONFIGURED for item in results)
        )
        self.assertTrue(
            all(item.evidence is EvidenceKind.NOT_VERIFIED for item in results)
        )
        self.assertEqual(results[0].message, "watsonx Orchestrate is not configured.")
        self.assertEqual(results[1].message, "Agent is not configured.")
        http.assert_exhausted()

    def test_wxo_reads_registered_agents_with_repeated_ids_and_marks_matches(self):
        environment = self._wxo_environment(
            WXO_SERVICE_INSTANCE_URL="https://wxo.example/instances/demo/"
        )
        http = self._wxo_http(
            "https://wxo.example/instances/demo",
            FakeResponse(
                200,
                {
                    "agents": [
                        {"id": AGENT_IDS[0], "name": "do not expose"},
                        {"id": AGENT_IDS[2]},
                    ]
                },
            ),
        )

        results = check_wxo(environment, http, CHECKED_AT)

        self.assertEqual(
            [item.status for item in results],
            [
                StatusValue.READY,
                StatusValue.READY,
                StatusValue.UNAVAILABLE,
                StatusValue.READY,
            ],
        )
        self.assertEqual(results[0].message, "watsonx Orchestrate is reachable.")
        self.assertEqual(results[1].message, "Agent is registered.")
        self.assertEqual(results[2].message, "Agent is not registered.")
        self.assertNotIn("do not expose", "".join(item.model_dump_json() for item in results))
        http.assert_exhausted()

    def test_wxo_checks_configured_agents_when_one_agent_id_is_missing(self):
        environment = self._wxo_environment(
            WXO_SERVICE_INSTANCE_URL="https://wxo.example/instances/demo",
            DOCUMENT_VALIDATION_AGENT_ID="",
        )
        configured_ids = (AGENT_IDS[0], AGENT_IDS[2])
        http = StrictHttp(
            [
                token_request(api_key="wxo-api-key"),
                (
                    "GET",
                    "https://wxo.example/instances/demo/v2/orchestrate/agents",
                    {
                        "headers": {"Authorization": "Bearer private-token"},
                        "params": [("ids", agent_id) for agent_id in configured_ids],
                        "timeout": (2, 3),
                    },
                    FakeResponse(200, {"agents": [{"id": AGENT_IDS[0]}]}),
                ),
            ]
        )

        results = check_wxo(environment, http, CHECKED_AT)

        self.assertEqual(
            [(item.status, item.evidence) for item in results],
            [
                (StatusValue.READY, EvidenceKind.LIVE_CHECK),
                (StatusValue.READY, EvidenceKind.LIVE_CHECK),
                (StatusValue.NOT_CONFIGURED, EvidenceKind.NOT_VERIFIED),
                (StatusValue.UNAVAILABLE, EvidenceKind.LIVE_CHECK),
            ],
        )
        self.assertEqual(results[2].message, "Agent is not configured.")
        http.assert_exhausted()

    def test_wxo_accepts_top_level_registered_agent_collection(self):
        environment = self._wxo_environment(
            WXO_SERVICE_INSTANCE_URL="https://wxo.example/instances/demo"
        )
        http = self._wxo_http(
            "https://wxo.example/instances/demo",
            FakeResponse(200, [{"id": agent_id} for agent_id in AGENT_IDS]),
        )

        results = check_wxo(environment, http, CHECKED_AT)

        self.assertTrue(all(item.status is StatusValue.READY for item in results))
        http.assert_exhausted()

    def test_wxo_unrecognized_success_schema_is_safely_unavailable(self):
        environment = self._wxo_environment(
            WXO_SERVICE_INSTANCE_URL="https://wxo.example/instances/demo"
        )
        http = self._wxo_http(
            "https://wxo.example/instances/demo",
            FakeResponse(200, {"unexpected": "private provider body"}),
        )

        with self.assertLogs("services.status_checks", level="WARNING") as captured:
            results = check_wxo(environment, http, CHECKED_AT)

        self.assertTrue(
            all(item.status is StatusValue.UNAVAILABLE for item in results)
        )
        self.assertNotIn(
            "private provider body",
            "".join(item.model_dump_json() for item in results),
        )
        self.assertEqual(
            captured.output,
            [
                "WARNING:services.status_checks:watsonx Orchestrate "
                "status check failed (_HTTPStatusFailure)"
            ],
        )
        http.assert_exhausted()

    def test_wxo_resolves_ibm_cloud_instance_root(self):
        environment = self._wxo_environment(
            WXO_INSTANCE_ID="instance-id",
            WXO_INSTANCE_CLOUD="ibmcloud",
            WXO_INSTANCE_CLOUD_REGION="eu-de",
        )
        root = (
            "https://api.eu-de.watson-orchestrate.cloud.ibm.com/instances/instance-id"
        )
        http = self._wxo_http(root, FakeResponse(200, {"agents": []}))

        check_wxo(environment, http, CHECKED_AT)

        http.assert_exhausted()

    def test_wxo_aws_uses_saas_json_token_contract_then_reads_registered_agents(self):
        environment = self._wxo_environment(
            WXO_INSTANCE_ID="aws-instance-id",
            WXO_INSTANCE_CLOUD="aws",
        )
        root = "https://api.dl.watson-orchestrate.ibm.com/instances/aws-instance-id"
        http = StrictHttp(
            [
                (
                    "POST",
                    AWS_IAM_URL,
                    {
                        "headers": {
                            "accept": "application/json",
                            "content-type": "application/json",
                        },
                        "data": json.dumps({"apikey": "wxo-api-key"}),
                        "timeout": (2, 3),
                    },
                    FakeResponse(200, {"token": "private-aws-token"}),
                ),
                (
                    "GET",
                    f"{root}/v2/orchestrate/agents",
                    {
                        "headers": {"Authorization": "Bearer private-aws-token"},
                        "params": [("ids", agent_id) for agent_id in AGENT_IDS],
                        "timeout": (2, 3),
                    },
                    FakeResponse(200, {"agents": [{"id": item} for item in AGENT_IDS]}),
                ),
            ]
        )

        results = check_wxo(environment, http, CHECKED_AT)

        self.assertTrue(all(item.status is StatusValue.READY for item in results))
        self.assertNotIn(
            "private-aws-token",
            "".join(item.model_dump_json() for item in results),
        )
        http.assert_exhausted()

    def test_wxo_resolves_software_instance_root(self):
        environment = self._wxo_environment(
            WXO_INSTANCE_ID="instance-id", WXO_INSTANCE_CLOUD="software"
        )
        root = "https://api.dl.watson-orchestrate.ibm.com/instances/instance-id"
        http = self._wxo_http(root, FakeResponse(200, {"agents": []}))

        check_wxo(environment, http, CHECKED_AT)

        http.assert_exhausted()

    def test_wxo_http_failure_marks_service_and_agents_unavailable(self):
        environment = self._wxo_environment(
            WXO_SERVICE_INSTANCE_URL="https://wxo.example/instances/demo"
        )
        for outcome in (
            FakeResponse(401, {"error": "private 401"}),
            FakeResponse(403, {"error": "private 403"}),
            FakeResponse(404, {"error": "private 404"}),
            FakeResponse(429, {"error": "private 429"}),
            FakeResponse(500, {"error": "private 500"}),
            TimeoutError("private timeout"),
        ):
            with self.subTest(outcome=type(outcome).__name__):
                http = self._wxo_http(
                    "https://wxo.example/instances/demo", outcome
                )

                with self.assertLogs(
                    "services.status_checks", level="WARNING"
                ) as captured:
                    results = check_wxo(environment, http, CHECKED_AT)

                self.assertTrue(
                    all(item.status is StatusValue.UNAVAILABLE for item in results)
                )
                self.assertTrue(
                    all(item.evidence is EvidenceKind.LIVE_CHECK for item in results)
                )
                self.assertEqual(
                    results[0].message, "watsonx Orchestrate is unavailable."
                )
                self.assertEqual(results[1].message, "Agent status is unavailable.")
                self.assertNotIn(
                    "private", "".join(item.model_dump_json() for item in results)
                )
                exception_name = (
                    "TimeoutError"
                    if isinstance(outcome, TimeoutError)
                    else "_HTTPStatusFailure"
                )
                self.assertEqual(
                    captured.output,
                    [
                        "WARNING:services.status_checks:watsonx Orchestrate "
                        f"status check failed ({exception_name})"
                    ],
                )
                http.assert_exhausted()

    def test_openllmetry_reports_configuration_and_initialization_state(self):
        cases = (
            ({}, False, StatusValue.NOT_CONFIGURED, EvidenceKind.NOT_VERIFIED,
             "OpenLLMetry is not configured."),
            ({"OPENLLMETRY_ENABLED": "true"}, True, StatusValue.READY,
             EvidenceKind.CONFIGURED, "OpenLLMetry is initialized."),
            ({"OPENLLMETRY_ENABLED": "yes"}, False, StatusValue.LIMITED,
             EvidenceKind.CONFIGURED, "OpenLLMetry is enabled but not initialized."),
        )
        for environment, initialized, status, evidence, message in cases:
            with self.subTest(status=status):
                result = check_openllmetry(environment, initialized, CHECKED_AT)

                self.assertIs(result.status, status)
                self.assertIs(result.evidence, evidence)
                self.assertEqual(result.message, message)
                self.assertEqual(result.checked_at, CHECKED_AT)

    @staticmethod
    def _wxo_environment(**overrides):
        environment = {
            "WXO_API_KEY": "wxo-api-key",
            "DOC_PROCESSOR_AGENT_ID": AGENT_IDS[0],
            "DOCUMENT_VALIDATION_AGENT_ID": AGENT_IDS[1],
            "FINAL_DECISION_AGENT_ID": AGENT_IDS[2],
        }
        environment.update(overrides)
        return environment

    @staticmethod
    def _wxo_http(root, outcome):
        return StrictHttp(
            [
                token_request(api_key="wxo-api-key"),
                (
                    "GET",
                    f"{root}/v2/orchestrate/agents",
                    {
                        "headers": {"Authorization": "Bearer private-token"},
                        "params": [
                            ("ids", AGENT_IDS[0]),
                            ("ids", AGENT_IDS[1]),
                            ("ids", AGENT_IDS[2]),
                        ],
                        "timeout": (2, 3),
                    },
                    outcome,
                ),
            ]
        )


if __name__ == "__main__":
    unittest.main()
