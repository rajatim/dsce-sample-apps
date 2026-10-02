"""Targeted checks must preserve unrelated evidence and bound provider work."""
import threading
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from test_system_status_service import FakeClock, build_checks, dependency
from services.system_status import SystemStatusService


def row(snapshot, name):
    return next(item for item in snapshot.dependencies if item.id == name)


class TargetedStatusTests(unittest.TestCase):
    def service(self, **kwargs):
        self.clock = FakeClock()
        self.calls = Counter()
        service = SystemStatusService(
            clock=self.clock, monotonic_clock=self.clock.monotonic,
            dependency_checks=build_checks(self.calls, kwargs.pop('overrides', None)), **kwargs,
        )
        self.addCleanup(service.close)
        return service

    def test_target_updates_only_selected_group_and_does_not_reage_other_rows(self):
        service = self.service()
        before = service.get_status()
        self.clock.advance(seconds=91)
        after = service.get_status(force_refresh=True, dependency_id='cos')
        self.assertEqual(self.calls['cos'], 2)
        self.assertEqual(self.calls['wxo'], 1)
        self.assertEqual(row(before, 'wxo').checked_at, row(after, 'wxo').checked_at)
        self.assertTrue(row(after, 'wxo').stale)
        self.assertFalse(row(after, 'cos').stale)
        self.assertEqual(after.refresh.affected_ids, ('cos',))
        self.assertGreater(after.revision, before.revision)
        self.assertNotEqual(after.overall.status.value, 'ready')

    def test_cold_target_does_not_contact_unselected_dependencies(self):
        service = self.service()
        after = service.get_status(force_refresh=True, dependency_id='cos')
        self.assertEqual(dict(self.calls), {'cos': 1})
        self.assertIsNone(row(after, 'wxo').checked_at)
        self.assertEqual(row(after, 'wxo').status.value, 'unknown')
        self.assertEqual(len(after.dependencies), 8)

    def test_agent_buttons_share_wxo_group_and_cooldown(self):
        service = self.service()
        first = service.get_status(force_refresh=True, dependency_id='document_processing_agent')
        second = service.get_status(force_refresh=True, dependency_id='final_decision_agent')
        self.assertEqual(dict(self.calls), {'wxo': 1})
        self.assertEqual(set(first.refresh.affected_ids), {'wxo', 'document_processing_agent', 'document_validation_agent', 'final_decision_agent'})
        self.assertEqual(second.refresh.result, 'cooldown')
        self.assertEqual(second.refresh.retry_after_seconds, 15)
        self.assertEqual(row(first, 'wxo').checked_at, row(second, 'wxo').checked_at)

    def test_api_check_does_not_call_database_or_providers(self):
        service = self.service()
        result = service.get_status(force_refresh=True, dependency_id='loan_api')
        self.assertFalse(self.calls)
        self.assertEqual(row(result, 'loan_api').status.value, 'ready')
        self.assertEqual(result.refresh.affected_ids, ('loan_api',))

    def test_concurrent_wxo_requests_share_one_operation(self):
        entered, release = threading.Event(), threading.Event()
        from test_system_status_service import ready_check_results
        def slow(now):
            entered.set()
            release.wait(1)
            return ready_check_results(now)['wxo']
        service = self.service(overrides={'wxo': slow})
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(service.get_status, True, name) for name in
                       ('wxo', 'document_processing_agent', 'document_validation_agent', 'final_decision_agent')]
            self.assertTrue(entered.wait(1))
            release.set()
            results = [f.result(2) for f in futures]
        self.assertEqual(self.calls['wxo'], 1)
        self.assertTrue(all(row(r, 'wxo').status.value == 'ready' for r in results))

    def test_lingering_job_result_keeps_original_check_time(self):
        entered, release = threading.Event(), threading.Event()
        def slow(now):
            entered.set()
            release.wait(1)
            return dependency('cos', now)
        service = self.service(overrides={'cos': slow}, total_check_budget_seconds=.01, force_refresh_cooldown_seconds=0)
        first = service.get_status(True, 'cos')
        self.assertTrue(entered.is_set())
        self.assertEqual(row(first, 'cos').problem.code, 'timeout')
        self.clock.advance(seconds=100)
        release.set()
        second = service.get_status(True, 'cos')
        self.assertEqual(self.calls['cos'], 1)
        self.assertEqual(row(first, 'cos').checked_at, row(second, 'cos').checked_at)
        self.assertTrue(row(second, 'cos').stale)

    def test_invalid_target_is_rejected_before_provider_calls(self):
        service = self.service()
        with self.assertRaises(ValueError):
            service.get_status(True, 'https://private.example')
        self.assertFalse(self.calls)
