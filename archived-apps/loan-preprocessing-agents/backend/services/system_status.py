"""Cached, privacy-safe orchestration for the Loan demo status endpoint."""

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
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


class SystemStatusService:
    """Run dependency checks once, share the result, and expose only public models."""

    def __init__(
        self,
        *,
        dependency_checks: Mapping[str, DependencyCheck],
        activity_loader: ActivityLoader = lambda: {},
        clock: Callable[[], datetime] = _utc_now,
        cache_ttl_seconds: float = 30,
        force_refresh_cooldown_seconds: float = 15,
        stale_after_seconds: int = 90,
        total_check_budget_seconds: float = 5,
    ) -> None:
        self._dependency_checks = dict(dependency_checks)
        self._activity_loader = activity_loader
        self._clock = clock
        self._cache_ttl_seconds = cache_ttl_seconds
        self._force_refresh_cooldown_seconds = force_refresh_cooldown_seconds
        self._stale_after_seconds = stale_after_seconds
        self._total_check_budget_seconds = total_check_budget_seconds
        self._refresh_lock = threading.Lock()
        self._cached: SystemStatusResponse | None = None

    def database_is_ready(self) -> bool:
        """Check only PostgreSQL for the readiness probe."""
        check = self._dependency_checks.get("postgresql")
        if check is None:
            return False
        try:
            result = check(self._clock())
        except Exception as error:
            self._log_failure("postgresql", error)
            return False
        return (
            isinstance(result, DependencyStatus)
            and result.id == "postgresql"
            and result.status is StatusValue.READY
        )

    def get_status(self, force_refresh: bool = False) -> SystemStatusResponse:
        now = self._clock()
        cached = self._reusable_cached(now, force_refresh)
        if cached is not None:
            return cached

        with self._refresh_lock:
            now = self._clock()
            cached = self._reusable_cached(now, force_refresh)
            if cached is not None:
                return cached

            response = self._refresh(now)
            self._cached = response
            return response

    def _reusable_cached(
        self, now: datetime, force_refresh: bool
    ) -> SystemStatusResponse | None:
        if self._cached is None:
            return None
        cache_age = self._age_seconds(now, self._cached.checked_at)
        if force_refresh:
            if cache_age >= self._force_refresh_cooldown_seconds:
                return None
        else:
            if cache_age >= self._cache_ttl_seconds:
                return None
        return self._with_current_staleness(self._cached, now)

    @staticmethod
    def _age_seconds(now: datetime, then: datetime) -> float:
        return max(0.0, (now - then).total_seconds())

    def _with_current_staleness(
        self, response: SystemStatusResponse, now: datetime
    ) -> SystemStatusResponse:
        stale = self._age_seconds(now, response.checked_at) >= self._stale_after_seconds
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
        executor = ThreadPoolExecutor(max_workers=len(_CHECK_ORDER) + 1)
        futures: dict[Future[object], str] = {}
        started = time.monotonic()
        try:
            for check_name in _CHECK_ORDER:
                check = self._dependency_checks.get(check_name)
                if check is None:
                    continue
                futures[executor.submit(check, checked_at)] = check_name
            futures[executor.submit(self._activity_loader)] = "activity"

            remaining = max(
                0.0,
                self._total_check_budget_seconds - (time.monotonic() - started),
            )
            done, unfinished = wait(futures, timeout=remaining)

            for future in unfinished:
                future.cancel()
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

                if check_name == "activity":
                    if isinstance(result, Mapping):
                        activity = result
                    continue
                if not self._add_check_result(dependencies, check_name, result):
                    self._add_fallback(
                        dependencies,
                        check_name,
                        checked_at,
                        status=StatusValue.UNAVAILABLE,
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

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

    @staticmethod
    def _expected_ids(check_name: str) -> tuple[str, ...]:
        return _WXO_DEPENDENCIES if check_name == "wxo" else (check_name,)

    def _add_check_result(
        self,
        dependencies: dict[str, DependencyStatus],
        check_name: str,
        result: object,
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
            updated[dependency_id] = current.model_copy(
                update={
                    "last_success_at": recent.last_success_at,
                    "last_failure_at": recent.last_failure_at,
                }
            )
        return updated

    @staticmethod
    def _log_failure(check_name: str, error: Exception) -> None:
        label = _LABELS.get(check_name, "Agent activity")
        LOGGER.warning("%s status orchestration failed (%s)", label, type(error).__name__)
