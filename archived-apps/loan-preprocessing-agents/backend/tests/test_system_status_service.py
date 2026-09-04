import threading
import time
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone

from repositories.status_activity import AgentActivity
from services.system_status import SystemStatusService
from status_models import DependencyStatus, EvidenceKind, StatusValue


STARTED_AT = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
DISPLAY_ORDER = [
    "loan_api",
    "postgresql",
    "cos",
    "watsonx_ai",
    "wxo",
    "document_processing_agent",
    "document_validation_agent",
    "final_decision_agent",
    "openllmetry",
]


class FakeClock:
    def __init__(self, current=STARTED_AT):
        self.current = current

    def __call__(self):
        return self.current

    def advance(self, *, seconds):
        self.current += timedelta(seconds=seconds)


def dependency(dependency_id, checked_at, status=StatusValue.READY):
    return DependencyStatus(
        id=dependency_id,
        label=dependency_id,
        status=status,
        evidence=EvidenceKind.LIVE_CHECK,
        message="Fixed test status.",
        checked_at=checked_at,
    )


def ready_check_results(checked_at):
    return {
        "postgresql": dependency("postgresql", checked_at),
        "cos": dependency("cos", checked_at),
        "watsonx_ai": dependency("watsonx_ai", checked_at),
        "wxo": [
            dependency("wxo", checked_at),
            dependency("document_processing_agent", checked_at),
            dependency("document_validation_agent", checked_at),
            dependency("final_decision_agent", checked_at),
        ],
        "openllmetry": dependency("openllmetry", checked_at),
    }


def build_checks(calls, overrides=None):
    overrides = overrides or {}

    def make_check(name):
        def check(checked_at):
            calls[name] += 1
            outcome = overrides.get(name, ready_check_results(checked_at)[name])
            return outcome(checked_at) if callable(outcome) else outcome

        return check

    return {
        name: make_check(name)
        for name in ("postgresql", "cos", "watsonx_ai", "wxo", "openllmetry")
    }


class SystemStatusServiceTests(unittest.TestCase):
    def make_service(self, *, clock=None, overrides=None, activity_loader=None, **values):
        self.calls = Counter()
        self.clock = clock or FakeClock()
        return SystemStatusService(
            clock=self.clock,
            dependency_checks=build_checks(self.calls, overrides),
            activity_loader=activity_loader or (lambda: {}),
            **values,
        )

    def test_reuses_cached_result_for_thirty_seconds(self):
        service = self.make_service()

        first = service.get_status()
        self.clock.advance(seconds=29)
        second = service.get_status()

        self.assertEqual(first.checked_at, second.checked_at)
        self.assertTrue(all(count == 1 for count in self.calls.values()))

        self.clock.advance(seconds=1)
        third = service.get_status()
        self.assertGreater(third.checked_at, second.checked_at)
        self.assertTrue(all(count == 2 for count in self.calls.values()))

    def test_force_refresh_is_throttled_for_fifteen_seconds(self):
        service = self.make_service()

        first = service.get_status(force_refresh=True)
        self.clock.advance(seconds=10)
        second = service.get_status(force_refresh=True)

        self.assertEqual(second.checked_at, first.checked_at)
        self.assertTrue(all(count == 1 for count in self.calls.values()))

        self.clock.advance(seconds=5)
        third = service.get_status(force_refresh=True)
        self.assertGreater(third.checked_at, second.checked_at)
        self.assertTrue(all(count == 2 for count in self.calls.values()))

    def test_one_timed_out_check_does_not_remove_other_results(self):
        release = threading.Event()

        def timed_out_wxo(checked_at):
            release.wait(timeout=1)
            return ready_check_results(checked_at)["wxo"]

        service = self.make_service(
            overrides={"wxo": timed_out_wxo},
            total_check_budget_seconds=0.05,
        )

        started = time.monotonic()
        try:
            result = service.get_status()
        finally:
            release.set()
        elapsed = time.monotonic() - started

        by_id = {item.id: item for item in result.dependencies}
        self.assertLess(elapsed, 0.4)
        self.assertIs(by_id["postgresql"].status, StatusValue.READY)
        self.assertIs(by_id["wxo"].status, StatusValue.UNKNOWN)
        self.assertIs(
            by_id["document_processing_agent"].status,
            StatusValue.UNKNOWN,
        )
        self.assertEqual([item.id for item in result.dependencies], DISPLAY_ORDER)

    def test_recent_activity_only_annotates_its_agent_and_never_overrides_live_failure(self):
        processor_success = STARTED_AT - timedelta(minutes=3)
        validator_failure = STARTED_AT - timedelta(minutes=1)

        def wxo_with_failed_processor(checked_at):
            results = ready_check_results(checked_at)["wxo"]
            results[1] = dependency(
                "document_processing_agent",
                checked_at,
                StatusValue.UNAVAILABLE,
            )
            return results

        service = self.make_service(
            overrides={"wxo": wxo_with_failed_processor},
            activity_loader=lambda: {
                "document_processing_agent": AgentActivity(
                    agent_key="document_processing_agent",
                    last_success_at=processor_success,
                ),
                "document_validation_agent": AgentActivity(
                    agent_key="document_validation_agent",
                    last_failure_at=validator_failure,
                ),
            },
        )

        result = service.get_status()

        by_id = {item.id: item for item in result.dependencies}
        self.assertIs(
            by_id["document_processing_agent"].status,
            StatusValue.UNAVAILABLE,
        )
        self.assertEqual(
            by_id["document_processing_agent"].last_success_at,
            processor_success,
        )
        self.assertIsNone(by_id["document_processing_agent"].last_failure_at)
        self.assertEqual(
            by_id["document_validation_agent"].last_failure_at,
            validator_failure,
        )
        self.assertIsNone(by_id["final_decision_agent"].last_success_at)
        self.assertIsNone(by_id["wxo"].last_success_at)

    def test_check_exception_uses_fixed_public_copy(self):
        private_values = (
            "secret-api-key",
            "https://private.example/internal",
            "instance-id-123",
            "raw provider exception",
        )

        def failed_check(checked_at):
            raise RuntimeError(" ".join(private_values))

        service = self.make_service(overrides={"watsonx_ai": failed_check})

        result = service.get_status()
        serialized = result.model_dump_json()

        by_id = {item.id: item for item in result.dependencies}
        self.assertIs(by_id["watsonx_ai"].status, StatusValue.UNAVAILABLE)
        for private_value in private_values:
            self.assertNotIn(private_value, serialized)

    def test_cached_response_is_marked_stale_at_ninety_seconds(self):
        service = self.make_service(cache_ttl_seconds=120)

        first = service.get_status()
        self.clock.advance(seconds=90)
        stale = service.get_status()

        self.assertFalse(first.stale)
        self.assertTrue(stale.stale)
        self.assertEqual(stale.checked_at, first.checked_at)

    def test_concurrent_requests_share_one_refresh(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_postgresql(checked_at):
            entered.set()
            release.wait(timeout=1)
            return dependency("postgresql", checked_at)

        service = self.make_service(overrides={"postgresql": slow_postgresql})
        results = []

        first = threading.Thread(target=lambda: results.append(service.get_status()))
        second = threading.Thread(
            target=lambda: results.append(service.get_status(force_refresh=True))
        )
        first.start()
        self.assertTrue(entered.wait(timeout=1))
        second.start()
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].checked_at, results[1].checked_at)
        self.assertTrue(all(count == 1 for count in self.calls.values()))


if __name__ == "__main__":
    unittest.main()
