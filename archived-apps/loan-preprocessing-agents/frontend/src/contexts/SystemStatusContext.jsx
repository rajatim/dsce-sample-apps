import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchSystemStatus } from '../services/systemStatus';
import { SystemStatusContext } from './useSystemStatus';

const relativeLabel = (status, now) => {
  if (!status?.checked_at) return '';
  const ageSeconds = Math.max(0, (now - Date.parse(status.checked_at)) / 1000);
  if (status.stale || ageSeconds >= status.stale_after_seconds) return 'Status data is out of date';
  if (ageSeconds < 60) return 'Checked just now';
  const minutes = Math.floor(ageSeconds / 60);
  return `Checked ${minutes} minute${minutes === 1 ? '' : 's'} ago`;
};

export const SystemStatusProvider = ({ children }) => {
  const [status, setStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const requestRef = useRef(null);
  const mountedRef = useRef(true);

  const load = useCallback((refresh = false) => {
    if (requestRef.current && !requestRef.current.controller.signal.aborted) return requestRef.current.promise;
    const controller = new AbortController();
    const promise = fetchSystemStatus({ refresh, signal: controller.signal })
      .then((nextStatus) => {
        if (mountedRef.current && requestRef.current?.promise === promise) {
          setStatus(nextStatus);
          setError('');
        }
        return nextStatus;
      })
      .catch((loadError) => {
        if (mountedRef.current && requestRef.current?.promise === promise && loadError?.name !== 'AbortError') {
          setError('Demo status is currently unavailable.');
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
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load().catch(() => {});
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
      if (requestRef.current) requestRef.current.controller.abort();
    };
  }, [load]);

  const refresh = useCallback(() => load(true), [load]);
  const checkedAtLabel = useMemo(() => relativeLabel(status, now), [status, now]);
  const value = useMemo(() => ({ status, isLoading, isRefreshing, error, refresh, checkedAtLabel }), [
    status, isLoading, isRefreshing, error, refresh, checkedAtLabel,
  ]);

  return <SystemStatusContext.Provider value={value}>{children}</SystemStatusContext.Provider>;
};
