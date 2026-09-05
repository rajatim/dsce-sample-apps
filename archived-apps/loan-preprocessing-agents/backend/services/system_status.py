"""Cached, privacy-safe orchestration for the Loan demo status endpoint."""

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass
from datetime import datetime, timezone

from repositories.status_activity import AgentActivity
from services.status_aggregation import build_capabilities, build_overall
from status_models import (
    DependencyStatus,
    EvidenceKind,
    StatusValue,
    SystemStatusResponse,
)


LOGGER = logging.getLogger(__name__)

DISPLAY_ORDER = (
    "loan_api",
    "postgresql",
    "cos",
    "watsonx_ai",
    "wxo",
    "document_processing_agent",
    "document_validation_agent",
    "final_decision_agent",
    "openllmetry",
)
_CHECK_ORDER = ("postgresql", "cos", "watsonx_ai", "wxo", "openllmetry")
_JOB_ORDER = (*_CHECK_ORDER, "activity")
_WXO_DEPENDENCIES = (
    "wxo",
    "document_processing_agent",
    "document_validation_agent",
    "final_decision_agent",
)
_AGENT_DEPENDENCIES = _WXO_DEPENDENCIES[1:]
_LABELS = {
    "loan_api": "Loan API",
    "postgresql": "PostgreSQL",
    "cos": "Cloud Object Storage",
    "watsonx_ai": "watsonx.ai",
    "wxo": "watsonx Orchestrate",
    "document_processing_agent": "Document processing agent",
    "document_validation_agent": "Document validation agent",
    "final_decision_agent": "Final decision agent",
    "openllmetry": "OpenLLMetry",
}
_UNKNOWN_MESSAGES = {
    dependency_id: f"{label} status check timed out."
    for dependency_id, label in _LABELS.items()
}
_UNAVAILABLE_MESSAGES = {
    dependency_id: f"{label} status check is unavailable."
    for dependency_id, label in _LABELS.items()
}

CheckResult = DependencyStatus | Sequence[DependencyStatus]
DependencyCheck = Callable[[datetime], CheckResult]
ActivityLoader = Callable[[], Mapping[str, AgentActivity]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class _CacheEntry:
    response: SystemStatusResponse
    checked_monotonic: float
    refresh_completed_monotonic: float


class SystemStatusService:
    """Run dependency checks once, share the result, and expose only public models."""

    def __init__(
        self,
        *,
        dependency_checks: Mapping[str, DependencyCheck],
        activity_loader: ActivityLoader = lambda: {},
        clock: Callable[[], datetime] = _utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
        cache_ttl_seconds: float = 30,
        force_refresh_cooldown_seconds: float = 15,
        stale_after_seconds: int = 90,
        total_check_budget_seconds: float = 5,
        readiness_budget_seconds: float = 3,
    ) -> None:
        self._dependency_checks = dict(dependency_checks)
        self._activity_loader = activity_loader
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._cache_ttl_seconds = cache_ttl_seconds
        self._force_refresh_cooldown_seconds = force_refresh_cooldown_seconds
        self._stale_after_seconds = stale_after_seconds
        self._total_check_budget_seconds = total_check_budget_seconds
        self._readiness_budget_seconds = readiness_budget_seconds
        self._refresh_lock = threading.Lock()
        self._in_flight_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=len(_JOB_ORDER),
            thread_name_prefix="loan-status",
        )
        self._in_flight: dict[str, Future[object]] = {}
        self._cache_entry: _CacheEntry | None = None

    def close(self) -> None:
        """Release the process-lifetime worker pool without waiting on I/O."""
        with self._in_flight_lock:
            for future in self._in_flight.values():
                future.cancel()
            self._in_flight.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def database_is_ready(self) -> bool:
        """Check only PostgreSQL for the readiness probe."""
        check = self._dependency_checks.get("postgresql")
        if check is None:
            return False
        future = self._get_or_submit_job("postgresql", self._clock())
        if future is None:
            return False
        try:
            result = future.result(timeout=max(0.0, self._readiness_budget_seconds))
        except TimeoutError:
            if future.done():
                self._release_completed_job("postgresql", future)
            return False
        except Exception as error:
            self._log_failure("postgresql", error)
            self._release_completed_job("postgresql", future)
            return False
        self._release_completed_job("postgresql", future)
        return (
            isinstance(result, DependencyStatus)
            and result.id == "postgresql"
            and result.status is StatusValue.READY
        )

    def get_status(self, force_refresh: bool = False) -> SystemStatusResponse:
        now = self._monotonic_clock()
        cached = self._reusable_cached(now, force_refresh)
        if cached is not None:
            return cached

        with self._refresh_lock:
            now = self._monotonic_clock()
            cached = self._reusable_cached(now, force_refresh)
            if cached is not None:
                return cached

            checked_at = self._clock()
            checked_monotonic = self._monotonic_clock()
            response = self._refresh(checked_at)
            self._cache_entry = _CacheEntry(
                response=response,
                checked_monotonic=checked_monotonic,
                refresh_completed_monotonic=self._monotonic_clock(),
            )
            return response

    def _reusable_cached(
        self, now: float, force_refresh: bool
    ) -> SystemStatusResponse | None:
        entry = self._cache_entry
        if entry is None:
            return None
        if force_refresh:
            completed_age = self._elapsed_seconds(
                now,
                entry.refresh_completed_monotonic,
            )
            if completed_age >= self._force_refresh_cooldown_seconds:
                return None
        else:
            cache_age = self._elapsed_seconds(
                now,
                entry.refresh_completed_monotonic,
            )
            if cache_age >= self._cache_ttl_seconds:
                return None
        return self._with_current_staleness(entry, now)

    @staticmethod
    def _elapsed_seconds(now: float, then: float) -> float:
        if now < then:
            return float("inf")
        return now - then

    def _with_current_staleness(
        self,
        entry: _CacheEntry,
        now: float,
    ) -> SystemStatusResponse:
        response = entry.response
        stale = (
            self._elapsed_seconds(now, entry.checked_monotonic)
            >= self._stale_after_seconds
        )
        if response.stale == stale:
            return response
        return response.model_copy(update={"stale": stale})

    def _refresh(self, checked_at: datetime) -> SystemStatusResponse:
        dependencies = {
            "loan_api": DependencyStatus(
                id="loan_api",
                label=_LABELS["loan_api"],
                status=StatusValue.READY,
                evidence=EvidenceKind.LIVE_CHECK,
                message="Loan API is responding.",
                checked_at=checked_at,
            )
        }
        activity: Mapping[str, AgentActivity] = {}
        futures: dict[Future[object], str] = {}
        started = time.monotonic()
        for check_name in _JOB_ORDER:
            future = self._get_or_submit_job(check_name, checked_at)
            if future is not None:
                futures[future] = check_name

        remaining = max(
            0.0,
            self._total_check_budget_seconds - (time.monotonic() - started),
        )
        done, unfinished = wait(futures, timeout=remaining)

        for future in unfinished:
            check_name = futures[future]
            if check_name != "activity":
                self._add_fallback(
                    dependencies,
                    check_name,
                    checked_at,
                    status=StatusValue.UNKNOWN,
                )

        for future in done:
            check_name = futures[future]
            try:
                result = future.result()
            except Exception as error:
                self._log_failure(check_name, error)
                if check_name != "activity":
                    self._add_fallback(
                        dependencies,
                        check_name,
                        checked_at,
                        status=StatusValue.UNAVAILABLE,
                    )
                continue
            finally:
                self._release_completed_job(check_name, future)

            if check_name == "activity":
                if isinstance(result, Mapping):
                    activity = result
                continue
            if not self._add_check_result(
                dependencies,
                check_name,
                result,
                checked_at,
            ):
                self._add_fallback(
                    dependencies,
                    check_name,
                    checked_at,
                    status=StatusValue.UNAVAILABLE,
                )

        for check_name in _CHECK_ORDER:
            if check_name not in self._dependency_checks:
                self._add_fallback(
                    dependencies,
                    check_name,
                    checked_at,
                    status=StatusValue.UNKNOWN,
                )

        dependencies = self._attach_activity(dependencies, activity)
        ordered = [dependencies[item_id] for item_id in DISPLAY_ORDER]
        dependency_map = {item.id: item for item in ordered}
        capabilities = build_capabilities(dependency_map)
        return SystemStatusResponse(
            overall=build_overall(capabilities),
            checked_at=checked_at,
            stale_after_seconds=self._stale_after_seconds,
            stale=False,
            capabilities=capabilities,
            dependencies=ordered,
        )

    def _get_or_submit_job(
        self,
        check_name: str,
        checked_at: datetime,
    ) -> Future[object] | None:
        with self._in_flight_lock:
            current = self._in_flight.get(check_name)
            if current is not None and not current.done():
                return current
            if current is not None:
                self._in_flight.pop(check_name, None)

            if check_name == "activity":
                operation: Callable[[], object] = self._activity_loader
            else:
                check = self._dependency_checks.get(check_name)
                if check is None:
                    return None
                operation = lambda: check(checked_at)

            try:
                future = self._executor.submit(operation)
            except RuntimeError:
                return None
            self._in_flight[check_name] = future
            return future

    def _release_completed_job(
        self,
        check_name: str,
        future: Future[object],
    ) -> None:
        if not future.done():
            return
        with self._in_flight_lock:
            if self._in_flight.get(check_name) is future:
                self._in_flight.pop(check_name, None)

    @staticmethod
    def _expected_ids(check_name: str) -> tuple[str, ...]:
        return _WXO_DEPENDENCIES if check_name == "wxo" else (check_name,)

    def _add_check_result(
        self,
        dependencies: dict[str, DependencyStatus],
        check_name: str,
        result: object,
        checked_at: datetime,
    ) -> bool:
        if isinstance(result, DependencyStatus):
            items = [result]
        elif isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
            items = list(result)
        else:
            return False
        expected_ids = self._expected_ids(check_name)
        if (
            len(items) != len(expected_ids)
            or not all(isinstance(item, DependencyStatus) for item in items)
            or {item.id for item in items} != set(expected_ids)
        ):
            return False
        items = [item.model_copy(update={"checked_at": checked_at}) for item in items]
        dependencies.update({item.id: item for item in items})
        return True

    def _add_fallback(
        self,
        dependencies: dict[str, DependencyStatus],
        check_name: str,
        checked_at: datetime,
        *,
        status: StatusValue,
    ) -> None:
        messages = (
            _UNKNOWN_MESSAGES
            if status is StatusValue.UNKNOWN
            else _UNAVAILABLE_MESSAGES
        )
        for dependency_id in self._expected_ids(check_name):
            dependencies[dependency_id] = DependencyStatus(
                id=dependency_id,
                label=_LABELS[dependency_id],
                status=status,
                evidence=EvidenceKind.LIVE_CHECK,
                message=messages[dependency_id],
                checked_at=checked_at,
            )

    @staticmethod
    def _attach_activity(
        dependencies: dict[str, DependencyStatus],
        activity: Mapping[str, AgentActivity],
    ) -> dict[str, DependencyStatus]:
        updated = dict(dependencies)
        for dependency_id in _AGENT_DEPENDENCIES:
            recent = activity.get(dependency_id)
            if not isinstance(recent, AgentActivity):
                continue
            current = updated[dependency_id]
            changes = {
                "last_success_at": recent.last_success_at,
                "last_failure_at": recent.last_failure_at,
            }
            latest_run_failed = (
                recent.last_failure_at is not None
                and (
                    recent.last_success_at is None
                    or recent.last_failure_at >= recent.last_success_at
                )
            )
            if current.status is StatusValue.READY and latest_run_failed:
                changes.update(
                    status=StatusValue.LIMITED,
                    evidence=EvidenceKind.RECENT_EXECUTION,
                    message="Agent is reachable, but its most recent run failed.",
                )
            updated[dependency_id] = current.model_copy(update=changes)
        return updated

    @staticmethod
    def _log_failure(check_name: str, error: Exception) -> None:
        label = _LABELS.get(check_name, "Agent activity")
        LOGGER.warning("%s status orchestration failed (%s)", label, type(error).__name__)
