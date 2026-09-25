import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchSystemStatus } from '../services/systemStatus';
import { SystemStatusContext } from './useSystemStatus';

const defaultWallClock = () => Date.now();
const defaultMonotonicClock = () => performance.now();

const timingFor = (snapshot, currentMonotonic, t) => {
  const status = snapshot?.status;
  if (!status?.checked_at) return { checkedAtLabel: '', isStale: false };

  const checkedAt = Date.parse(status.checked_at);
  const receiptAge = snapshot.receivedWall - checkedAt;
  const elapsed = currentMonotonic >= snapshot.receivedMonotonic
    ? currentMonotonic - snapshot.receivedMonotonic
    : Number.POSITIVE_INFINITY;
  const staleAfter = Number(status.stale_after_seconds) * 1000;
  const invalidTiming = !Number.isFinite(checkedAt)
    || !Number.isFinite(receiptAge)
    || receiptAge < 0
    || !Number.isFinite(staleAfter)
    || staleAfter <= 0;
  const ageMilliseconds = invalidTiming
    ? Number.POSITIVE_INFINITY
    : receiptAge + elapsed;
  const isStale = Boolean(status.stale)
    || invalidTiming
    || !Number.isFinite(elapsed)
    || ageMilliseconds >= staleAfter;

  if (isStale) {
    return { checkedAtLabel: t('timing.stale'), isStale: true };
  }
  const ageSeconds = Math.max(0, ageMilliseconds / 1000);
  if (ageSeconds < 60) {
    return { checkedAtLabel: t('timing.justNow'), isStale: false };
  }
  const minutes = Math.floor(ageSeconds / 60);
  return {
    checkedAtLabel: t('timing.minutesAgo', { count: minutes }),
    isStale: false,
  };
};

export const SystemStatusProvider = ({
  children,
  wallClock = defaultWallClock,
  monotonicClock = defaultMonotonicClock,
}) => {
  const { t } = useTranslation('status');
  const [snapshot, setSnapshot] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorKey, setErrorKey] = useState('');
  const [currentMonotonic, setCurrentMonotonic] = useState(() => monotonicClock());
  const requestRef = useRef(null);
  const mountedRef = useRef(true);

  const load = useCallback((refresh = false) => {
    if (requestRef.current && !requestRef.current.controller.signal.aborted) return requestRef.current.promise;
    const controller = new AbortController();
    const promise = fetchSystemStatus({ refresh, signal: controller.signal })
      .then((nextStatus) => {
        if (mountedRef.current && requestRef.current?.promise === promise) {
          const receivedWall = wallClock();
          const receivedMonotonic = monotonicClock();
          setSnapshot(Object.freeze({
            status: nextStatus,
            receivedWall,
            receivedMonotonic,
          }));
          setCurrentMonotonic(receivedMonotonic);
          setErrorKey('');
        }
        return nextStatus;
      })
      .catch((loadError) => {
        if (mountedRef.current && requestRef.current?.promise === promise && loadError?.name !== 'AbortError') {
          setErrorKey('errors.unavailable');
        }
        throw loadError;
      })
      .finally(() => {
        if (!mountedRef.current || requestRef.current?.promise !== promise) return;
        setIsLoading(false);
        setIsRefreshing(false);
        if (requestRef.current?.promise === promise) requestRef.current = null;
      });
    requestRef.current = { controller, promise };
    if (refresh) setIsRefreshing(true);
    return promise;
  }, [monotonicClock, wallClock]);

  useEffect(() => {
    mountedRef.current = true;
    load().catch(() => {});
    const timer = setInterval(() => setCurrentMonotonic(monotonicClock()), 30_000);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
      if (requestRef.current) requestRef.current.controller.abort();
    };
  }, [load, monotonicClock]);

  const refresh = useCallback(() => load(true), [load]);
  const status = snapshot?.status || null;
  const { checkedAtLabel, isStale } = useMemo(
    () => timingFor(snapshot, currentMonotonic, t),
    [currentMonotonic, snapshot, t],
  );
  const error = errorKey ? t(errorKey) : '';
  const value = useMemo(() => ({
    status,
    isLoading,
    isRefreshing,
    error,
    refresh,
    checkedAtLabel,
    isStale,
  }), [
    status, isLoading, isRefreshing, error, refresh, checkedAtLabel, isStale,
  ]);

  return <SystemStatusContext.Provider value={value}>{children}</SystemStatusContext.Provider>;
};
