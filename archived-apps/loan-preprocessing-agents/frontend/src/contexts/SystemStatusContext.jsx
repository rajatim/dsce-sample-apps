import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchSystemStatus } from '../services/systemStatus';
import { SystemStatusContext } from './useSystemStatus';

const wallClockDefault = () => Date.now();
const monotonicDefault = () => performance.now();
const groupFor = (id) => ['wxo', 'document_processing_agent', 'document_validation_agent', 'final_decision_agent'].includes(id) ? 'wxo' : id || 'all';

const ageOf = (item, snapshot, now) => {
  if (!snapshot || !item?.checked_at) return Infinity;
  const elapsed = now - snapshot.receivedMonotonic;
  if (elapsed < 0) return Infinity;
  const receivedAge = Number.isFinite(item.age_seconds)
    ? item.age_seconds * 1000 : snapshot.receivedWall - Date.parse(item.checked_at);
  return Number.isFinite(receivedAge) && receivedAge >= 0 ? receivedAge + elapsed : Infinity;
};

export const SystemStatusProvider = ({ children, wallClock = wallClockDefault, monotonicClock = monotonicDefault }) => {
  const { t } = useTranslation('status');
  const [snapshot, setSnapshot] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pending, setPending] = useState({});
  const [errors, setErrors] = useState({});
  const [outcomes, setOutcomes] = useState({});
  const [now, setNow] = useState(monotonicClock);
  const requests = useRef(new Map());
  const mounted = useRef(true);
  const retiredInstances = useRef(new Set());

  const load = useCallback((refresh = false, dependency) => {
    const group = groupFor(dependency);
    const existing = requests.current.get('all') || requests.current.get(group);
    if (existing && !existing.controller.signal.aborted) return existing.promise;
    const controller = new AbortController();
    const request = { controller };
    setPending((value) => ({ ...value, [group]: true }));
    setErrors((value) => ({ ...value, [group]: '' }));
    setOutcomes((value) => ({ ...value, [group]: null }));
    request.promise = fetchSystemStatus({ refresh, dependency, signal: controller.signal })
      .then((status) => {
        if (!mounted.current || requests.current.get(group) !== request) return status;
        const receivedWall = wallClock();
        const receivedMonotonic = monotonicClock();
        setSnapshot((previous) => {
          if (status.instance_id && retiredInstances.current.has(status.instance_id)) return previous;
          if (previous?.status.instance_id && status.instance_id === previous.status.instance_id
              && status.revision <= previous.status.revision) return previous;
          if (previous?.status.instance_id && status.instance_id && status.instance_id !== previous.status.instance_id) {
            retiredInstances.current.add(previous.status.instance_id);
          }
          return { status, receivedWall, receivedMonotonic };
        });
        setNow(receivedMonotonic);
        setOutcomes((value) => ({ ...value, [group]: status.refresh }));
        return status;
      })
      .catch((error) => {
        if (mounted.current && requests.current.get(group) === request && !controller.signal.aborted) {
          setErrors((value) => ({ ...value, [group]: 'errors.unavailable' }));
        }
        throw error;
      })
      .finally(() => {
        if (!mounted.current || requests.current.get(group) !== request) return;
        requests.current.delete(group);
        setIsLoading(false);
        setPending((value) => ({ ...value, [group]: false }));
      });
    requests.current.set(group, request);
    return request.promise;
  }, [wallClock, monotonicClock]);

  useEffect(() => {
    mounted.current = true;
    load().catch(() => {});
    const timer = setInterval(() => setNow(monotonicClock()), 30_000);
    const activeRequests = requests.current;
    return () => {
      mounted.current = false;
      clearInterval(timer);
      for (const request of activeRequests.values()) request.controller.abort();
      activeRequests.clear();
    };
  }, [load, monotonicClock]);

  const status = snapshot?.status || null;
  const isDependencyStale = useCallback((item) => Boolean(item.stale)
    || ageOf(item, snapshot, now) >= (status?.stale_after_seconds || 90) * 1000, [snapshot, now, status]);
  const isCapabilityStale = useCallback((item) => {
    if (item.age_seconds === undefined) return Boolean(status?.stale) || ageOf(status, snapshot, now) >= (status?.stale_after_seconds || 90) * 1000;
    const elapsed = snapshot ? now - snapshot.receivedMonotonic : Infinity;
    return Boolean(item.stale) || elapsed < 0 || item.age_seconds * 1000 + elapsed >= (status?.stale_after_seconds || 90) * 1000;
  }, [status, snapshot, now]);
  const age = ageOf(status, snapshot, now);
  const isStale = status ? (status.dependencies.length
    ? status.dependencies.some(isDependencyStale)
    : Boolean(status.stale) || age >= status.stale_after_seconds * 1000) : false;
  const checkedAtLabel = !status ? '' : isStale ? t('timing.stale') : age < 60_000
    ? t('timing.justNow') : t('timing.minutesAgo', { count: Math.floor(age / 60_000) });
  const refresh = useCallback(() => load(true), [load]);
  const checkDependency = useCallback((id) => load(true, id), [load]);
  const isChecking = useCallback((id) => Boolean(pending.all || pending[groupFor(id)]), [pending]);
  const checkError = useCallback((id) => errors[groupFor(id)] ? t(errors[groupFor(id)]) : '', [errors, t]);
  const checkOutcome = useCallback((id) => outcomes[groupFor(id)], [outcomes]);
  const value = useMemo(() => ({
    status, isLoading, isRefreshing: Boolean(pending.all), error: errors.all ? t(errors.all) : '',
    refresh, checkDependency, checkedAtLabel, isStale, isDependencyStale, isCapabilityStale, isChecking, checkError, checkOutcome,
    refreshOutcome: outcomes.all,
  }), [status, isLoading, pending.all, errors.all, t, refresh, checkDependency, checkedAtLabel,
    isStale, isDependencyStale, isCapabilityStale, isChecking, checkError, checkOutcome, outcomes.all]);
  return <SystemStatusContext.Provider value={value}>{children}</SystemStatusContext.Provider>;
};
