"""Bounded dependency checks with shared work and independent evidence ages."""
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextvars import copy_context
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass
from datetime import datetime, timezone

from repositories.status_activity import AgentActivity
from services.status_aggregation import build_capabilities, build_overall
from services.status_errors import problem_for, problem_from_exception
from status_models import DependencyStatus, EvidenceKind, RefreshResult, StatusValue, SystemStatusResponse

LOGGER = logging.getLogger(__name__)
_WXO_DEPENDENCIES = ('wxo', 'document_processing_agent', 'document_validation_agent', 'final_decision_agent')
_AGENT_DEPENDENCIES = _WXO_DEPENDENCIES[1:]
DISPLAY_ORDER = ('loan_api', 'postgresql', 'cos', 'watsonx_ai', *_WXO_DEPENDENCIES)
_GROUPS = ('loan_api', 'postgresql', 'cos', 'watsonx_ai', 'wxo')
_LABELS = dict(zip(DISPLAY_ORDER, ('Loan API', 'PostgreSQL', 'Cloud Object Storage', 'watsonx.ai',
                                  'watsonx Orchestrate', 'Document processing agent',
                                  'Document validation agent', 'Final decision agent')))
_KINDS = {'loan_api': 'api_response', 'postgresql': 'database_query', 'cos': 'bucket_metadata',
          'watsonx_ai': 'deployment_metadata', **{name: 'agent_registration' for name in _WXO_DEPENDENCIES}}
DependencyCheck = Callable[[datetime], DependencyStatus | Sequence[DependencyStatus]]
ActivityLoader = Callable[[], Mapping[str, AgentActivity]]


@dataclass(frozen=True)
class _Job:
    future: Future
    checked_at: datetime
    started: float


class SystemStatusService:
    def __init__(self, *, dependency_checks: Mapping[str, DependencyCheck],
                 activity_loader: ActivityLoader = lambda: {},
                 clock=lambda: datetime.now(timezone.utc), monotonic_clock=time.monotonic,
                 cache_ttl_seconds=30, force_refresh_cooldown_seconds=15,
                 stale_after_seconds=90, total_check_budget_seconds=5, readiness_budget_seconds=3):
        self._dependency_checks = dict(dependency_checks)
        self._activity_loader = activity_loader
        self._clock, self._monotonic_clock = clock, monotonic_clock
        self._cache_ttl_seconds = cache_ttl_seconds
        self._force_refresh_cooldown_seconds = force_refresh_cooldown_seconds
        self._stale_after_seconds = stale_after_seconds
        self._total_check_budget_seconds = total_check_budget_seconds
        self._readiness_budget_seconds = readiness_budget_seconds
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix='loan-status')
        self._jobs: dict[str, _Job] = {}
        self._completed: dict[str, float] = {}
        self._started: dict[str, float] = {}
        self._rows = {name: DependencyStatus(id=name, label=_LABELS[name], status=StatusValue.UNKNOWN,
                      evidence=EvidenceKind.NOT_VERIFIED, message='Not checked.', check_kind=_KINDS[name], stale=True)
                      for name in DISPLAY_ORDER}
        self._activity: Mapping[str, AgentActivity] = {}
        self._revision = 0
        self._instance_id = str(uuid.uuid4())
        self._assembled_at = self._clock()

    def close(self):
        with self._lock:
            for job in self._jobs.values():
                job.future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _elapsed_seconds(now, then):
        return now - then if now >= then else float('inf')

    @staticmethod
    def _ids(group):
        return _WXO_DEPENDENCIES if group == 'wxo' else (group,)

    def _job(self, group):
        """Call under the state lock. A completed but unpublished job is still reused."""
        if group in self._jobs:
            return self._jobs[group], True
        check = self._activity_loader if group == 'activity' else self._dependency_checks.get(group)
        if check is None:
            return None, False
        checked_at, started = self._clock(), self._monotonic_clock()
        def run():
            return check() if group == 'activity' else check(checked_at)
        job = _Job(self._executor.submit(copy_context().run, run), checked_at, started)
        self._jobs[group] = job
        return job, False

    def database_is_ready(self):
        with self._lock:
            job, _ = self._job('postgresql')
        if job is None:
            return False
        try:
            result = job.future.result(timeout=max(0, self._readiness_budget_seconds))
            ready = isinstance(result, DependencyStatus) and result.id == 'postgresql' and result.status is StatusValue.READY
        except TimeoutError:
            return False
        except Exception:
            ready = False
        with self._lock:
            self._publish('postgresql', job)
        return ready

    def get_status(self, force_refresh=False, dependency_id=None):
        if dependency_id is not None and (dependency_id not in DISPLAY_ORDER or not force_refresh):
            raise ValueError('Invalid dependency check request')
        requested_groups = ((_WXO_DEPENDENCIES[0] if dependency_id in _WXO_DEPENDENCIES else dependency_id),) if dependency_id else _GROUPS
        selected: dict[str, _Job] = {}
        affected = []
        reused = False
        executed = False
        cooldowns = []
        with self._lock:
            now = self._monotonic_clock()
            for group in requested_groups:
                affected.extend(self._ids(group))
                threshold = self._force_refresh_cooldown_seconds if force_refresh else self._cache_ttl_seconds
                remaining = threshold - self._elapsed_seconds(now, self._completed[group]) if group in self._completed else 0
                if remaining > 0:
                    cooldowns.append(math.ceil(remaining))
                    continue
                if group == 'loan_api':
                    checked_at = self._clock()
                    self._rows[group] = DependencyStatus(id=group, label=_LABELS[group], status=StatusValue.READY,
                        evidence=EvidenceKind.LIVE_CHECK, message='Loan API is responding.', checked_at=checked_at,
                        check_kind=_KINDS[group])
                    self._started[group] = now
                    self._completed[group] = now
                    self._changed()
                    executed = True
                    continue
                job, shared = self._job(group)
                if job is not None:
                    selected[group] = job
                    reused |= shared
                    executed |= not shared
                else:
                    self._set_problem(group, self._clock(), now,
                        problem_for(service=group, stage='configuration', code='missing_configuration'),
                        StatusValue.NOT_CONFIGURED)
                    self._completed[group] = now
                    executed = True
            if 'wxo' in selected:
                job, _ = self._job('activity')
                if job is not None:
                    selected['activity'] = job

        if selected:
            wait([job.future for job in selected.values()], timeout=max(0, self._total_check_budget_seconds))
        with self._lock:
            for group, job in selected.items():
                if job.future.done():
                    self._publish(group, job)
                elif group != 'activity' and self._jobs.get(group) is job:
                    # The timeout is evidence about this attempt, not a new provider call.
                    self._set_problem(group, job.checked_at, job.started,
                        problem_for(service=group, stage='orchestration', code='timeout'), StatusValue.UNKNOWN)
            refresh = None
            if force_refresh:
                refresh = RefreshResult(requested_dependency=dependency_id, affected_ids=tuple(affected),
                    result='executed' if executed else 'shared' if reused else 'cooldown',
                    retry_after_seconds=max(cooldowns, default=0) if not (executed or reused) else 0)
            return self._snapshot(refresh)

    def _changed(self):
        self._revision += 1
        self._assembled_at = self._clock()

    def _set_problem(self, group, checked_at, started, problem, status):
        for name in self._ids(group):
            blocked = name in _AGENT_DEPENDENCIES and group == 'wxo'
            old = self._rows[name]
            self._rows[name] = DependencyStatus(
                id=name, label=_LABELS[name], status=status,
                evidence=EvidenceKind.NOT_VERIFIED if blocked else EvidenceKind.LIVE_CHECK,
                message=f'{_LABELS[name]} check did not complete.', checked_at=checked_at,
                check_kind=_KINDS[name], problem=problem.model_copy(update={'blocked_by': 'wxo'}) if blocked else problem,
                last_success_at=old.last_success_at, last_failure_at=old.last_failure_at,
            )
            self._started[name] = started
        self._changed()

    def _publish(self, group, job):
        if self._jobs.get(group) is not job:
            return  # Another waiter already published this exact operation.
        try:
            result = job.future.result()
            if group == 'activity':
                if isinstance(result, Mapping):
                    self._activity = result
                    self._changed()
                return
            items = [result] if isinstance(result, DependencyStatus) else list(result)
            if (not all(isinstance(item, DependencyStatus) for item in items)
                    or len(items) != len(self._ids(group))
                    or {item.id for item in items} != set(self._ids(group))):
                raise ValueError('Invalid check result')
            for item in items:
                old = self._rows[item.id]
                self._rows[item.id] = item.model_copy(update={
                    'checked_at': job.checked_at, 'check_kind': _KINDS[item.id],
                    'last_success_at': old.last_success_at, 'last_failure_at': old.last_failure_at,
                })
                self._started[item.id] = job.started
            self._changed()
        except Exception as error:
            LOGGER.warning('%s status check did not complete', _LABELS.get(group, 'Agent activity'))
            if group != 'activity':
                self._set_problem(group, job.checked_at, job.started,
                    problem_from_exception(service=group, stage='orchestration', error=error), StatusValue.UNAVAILABLE)
        finally:
            self._jobs.pop(group, None)
            self._completed[group] = self._monotonic_clock()

    def _snapshot(self, refresh):
        now = self._monotonic_clock()
        rows = {}
        for name, item in self._rows.items():
            age = self._elapsed_seconds(now, self._started[name]) if name in self._started else float('inf')
            rows[name] = item.model_copy(update={'stale': age >= self._stale_after_seconds,
                'age_seconds': age if math.isfinite(age) else float(self._stale_after_seconds)})
        rows = self._attach_activity(rows, self._activity)
        capabilities = build_capabilities(rows)
        return SystemStatusResponse(overall=build_overall(capabilities), checked_at=self._assembled_at,
            stale_after_seconds=self._stale_after_seconds, stale=any(item.stale for item in rows.values()),
            capabilities=capabilities, dependencies=[rows[name] for name in DISPLAY_ORDER],
            revision=self._revision, instance_id=self._instance_id, refresh=refresh)

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
