import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from services.status_checks import check_postgresql
from services.system_status import SystemStatusService
from status_models import SystemStatusResponse


class StrictReadinessSession:
    def __init__(self, outcome=None):
        self.outcome = outcome
        self.statements = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def get_bind(self):
        return self.bind

    def execute(self, statement):
        sql = str(statement)
        if sql != "SELECT 1":
            raise AssertionError(f"Readiness must only run SELECT 1, got {sql!r}")
        self.statements.append(sql)
        if self.outcome is not None:
            raise self.outcome


def readiness_service(session):
    return SystemStatusService(
        dependency_checks={
            "postgresql": lambda checked_at: check_postgresql(
                lambda: session, checked_at
            )
        }
    )


class RecordingStatusService:
    def __init__(self, response):
        self.response = response
        self.force_refresh_values = []

    def get_status(self, force_refresh=False):
        self.force_refresh_values.append(force_refresh)
        return self.response


class StatusEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_healthz_is_exact_and_never_touches_dependency_checks(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("healthz must stay shallow")

        names = (
            "check_postgresql",
            "check_cos",
            "check_watsonx",
            "check_wxo",
            "check_openllmetry",
            "get_recent_agent_activity",
        )
        patches = [patch.object(main, name, forbidden) for name in names]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz_returns_ready_after_only_select_one(self):
        session = StrictReadinessSession()

        with patch.object(main, "system_status_service", readiness_service(session)):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        self.assertEqual(session.statements, ["SELECT 1"])

    def test_readyz_returns_only_safe_body_on_database_failure(self):
        session = StrictReadinessSession(
            RuntimeError("postgresql://private-user:private-password@private-host/db")
        )

        with patch.object(main, "system_status_service", readiness_service(session)):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "not_ready"})
        self.assertNotIn("private", response.text)
        self.assertEqual(session.statements, ["SELECT 1"])

    def test_system_status_is_public_and_matches_the_response_contract(self):
        safe_service = SystemStatusService(
            dependency_checks={
                name: (lambda checked_at: (_ for _ in ()).throw(
                    RuntimeError("safe test failure")
                ))
                for name in (
                    "postgresql",
                    "cos",
                    "watsonx_ai",
                    "wxo",
                    "openllmetry",
                )
            },
            activity_loader=lambda: {},
        )

        with patch.object(main, "system_status_service", safe_service):
            response = self.client.get("/system-status")

        self.assertEqual(response.status_code, 200)
        validated = SystemStatusResponse.model_validate(response.json())
        self.assertEqual(validated.stale_after_seconds, 90)
        self.assertNotIn("WWW-Authenticate", response.headers)

    def test_system_status_never_serializes_supplied_private_values(self):
        private_values = (
            "fake-api-secret-123",
            "https://private.example/wxo",
            "fake-project-id-456",
            "fake-agent-id-789",
            "raw exception detail",
        )

        def failed_check(checked_at):
            raise RuntimeError(" ".join(private_values))

        service = SystemStatusService(
            dependency_checks={
                name: failed_check
                for name in (
                    "postgresql",
                    "cos",
                    "watsonx_ai",
                    "wxo",
                    "openllmetry",
                )
            },
            activity_loader=lambda: {},
        )

        with patch.object(main, "system_status_service", service):
            response = self.client.get("/system-status")

        self.assertEqual(response.status_code, 200)
        for private_value in private_values:
            self.assertNotIn(private_value, response.text)

    def test_refresh_true_requests_a_forced_service_refresh(self):
        seed_service = SystemStatusService(
            dependency_checks={
                name: (lambda checked_at: (_ for _ in ()).throw(RuntimeError()))
                for name in (
                    "postgresql",
                    "cos",
                    "watsonx_ai",
                    "wxo",
                    "openllmetry",
                )
            },
            activity_loader=lambda: {},
        )
        recorder = RecordingStatusService(seed_service.get_status())

        with patch.object(main, "system_status_service", recorder):
            response = self.client.get("/system-status?refresh=true")

        self.assertEqual(response.status_code, 200)
        SystemStatusResponse.model_validate(response.json())
        self.assertEqual(recorder.force_refresh_values, [True])


if __name__ == "__main__":
    unittest.main()
