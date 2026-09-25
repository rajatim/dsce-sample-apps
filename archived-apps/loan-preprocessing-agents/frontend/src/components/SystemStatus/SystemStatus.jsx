import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Accordion,
  AccordionItem,
  Button,
  InlineLoading,
  Tag,
} from '@carbon/react';
import {
  CheckmarkFilled,
  ErrorFilled,
  Renew,
  UnknownFilled,
  WarningAltFilled,
} from '@carbon/react/icons';
import { useSystemStatus } from '../../contexts/useSystemStatus';
import { formatDateTime } from '../../i18n/format';
import './SystemStatus.css';

const CAPABILITIES = ['submit_application', 'process_documents', 'generate_decision', 'view_applications'];

const DEPENDENCIES = ['loan_api', 'postgresql', 'cos', 'watsonx_ai', 'wxo', 'document_processing_agent', 'document_validation_agent', 'final_decision_agent', 'openllmetry'];
const AGENT_DEPENDENCY_IDS = new Set([
  'document_processing_agent',
  'document_validation_agent',
  'final_decision_agent',
]);

const STATUS_PRESENTATION = {
  ready: { tag: 'green', Icon: CheckmarkFilled },
  limited: { tag: 'warm-gray', Icon: WarningAltFilled },
  unavailable: { tag: 'red', Icon: ErrorFilled },
  checking: { tag: 'blue', Icon: Renew },
  unknown: { tag: 'gray', Icon: UnknownFilled },
  not_configured: { tag: 'red', Icon: ErrorFilled },
};
const AUTO_REFRESH_INTERVAL_MS = 300_000;

const StatusMark = ({ status, large = false }) => {
  const { t } = useTranslation('status');
  const presentation = STATUS_PRESENTATION[status] || STATUS_PRESENTATION.unknown;
  const Icon = presentation.Icon;

  return (
    <span className={`system-status-mark system-status-mark--${status || 'unknown'}`}>
      <Icon size={large ? 32 : 20} aria-hidden="true" />
      <Tag size="sm" type={presentation.tag}>{t(`statuses.${STATUS_PRESENTATION[status] ? status : 'unknown'}`)}</Tag>
    </span>
  );
};

const capabilityItems = (status, isStale, t) => CAPABILITIES.map((id) => {
  const capability = status?.capabilities.find((item) => item.id === id);
  const itemStatus = isStale ? 'unknown' : capability?.status || 'unknown';
  const fallbackMessage = t(`capabilities.fallbacks.${id}`);
  const knownMessage = ['ready', 'limited', 'unavailable', 'not_configured'].includes(itemStatus);
  const quotaBlocked = capability?.problem?.provider_code === 'token_quota_reached';
  return {
    id,
    label: t(`capabilities.labels.${id}`),
    status: itemStatus,
    message: !isStale && quotaBlocked
      ? t(`capabilities.problemMessages.provider_quota.${id}`, { defaultValue: fallbackMessage })
      : isStale
      ? fallbackMessage
      : knownMessage
        ? t(`capabilities.messages.${id}.${itemStatus}`)
        : capability?.message || fallbackMessage,
    problem: isStale ? null : capability?.problem,
  };
});

const dependencyItems = (status, isStale, t) => DEPENDENCIES.flatMap((id) => {
  const dependency = status?.dependencies.find((item) => item.id === id);
  return dependency ? [{
    ...dependency,
    id,
    label: t(`dependencies.${id}`),
    status: isStale ? 'unknown' : dependency.status,
  }] : [];
});

const dependencyTiming = (dependency, t, locale) => {
  if (AGENT_DEPENDENCY_IDS.has(dependency.id)) {
    const lastSuccess = Date.parse(dependency.last_success_at);
    const lastFailure = Date.parse(dependency.last_failure_at);
    const hasSuccess = Number.isFinite(lastSuccess);
    const hasFailure = Number.isFinite(lastFailure);
    if (hasFailure && (!hasSuccess || lastFailure >= lastSuccess)) {
      return t('timing.lastFailed', { time: formatDateTime(dependency.last_failure_at, locale) });
    }
    if (hasSuccess) {
      return t('timing.lastSuccessful', { time: formatDateTime(dependency.last_success_at, locale) });
    }
    return t('timing.noRecentRun');
  }
  if (dependency.checked_at) {
    return t('timing.checkedAt', { time: formatDateTime(dependency.checked_at, locale) });
  }
  if (dependency.evidence === 'recent_execution') return t('timing.noRecentRun');
  return t('timing.noRecentCheck');
};

const dependencyMessage = (dependency, t) => {
  if (dependency.problem?.provider_code === 'token_quota_reached') {
    return t('problems.provider_quota.dependencyMessage');
  }
  if (!STATUS_PRESENTATION[dependency.status]) return dependency.message;
  const group = AGENT_DEPENDENCY_IDS.has(dependency.id)
    ? 'agent'
    : dependency.id === 'openllmetry' ? 'openllmetry' : 'service';
  return t(`dependencyMessages.${group}.${dependency.status}`, { label: dependency.label });
};

const statusCodeLabel = (status) => (
  status === 403 ? '403 Forbidden' : status ? String(status) : '—'
);

const DependencyProblem = ({ problem }) => {
  const { t } = useTranslation('status');
  if (!problem) return null;
  return (
    <dl className="system-status-problem">
      <div>
        <dt>{t('problems.fields.code')}</dt>
        <dd><code>{problem.provider_code}</code></dd>
      </div>
      <div>
        <dt>{t('problems.fields.httpStatus')}</dt>
        <dd><code>{statusCodeLabel(problem.http_status)}</code></dd>
      </div>
      {problem.trace_id && (
        <div>
          <dt>{t('problems.fields.traceId')}</dt>
          <dd><code>{problem.trace_id}</code></dd>
        </div>
      )}
    </dl>
  );
};

const overallPresentation = (overall, t) => {
  if (!overall) return null;
  if (!['ready', 'limited', 'unavailable'].includes(overall.status)) return overall;
  return {
    status: overall.status,
    title: t(`overall.${overall.status}.title`),
    message: t(`overall.${overall.status}.message`),
  };
};

const SystemStatus = () => {
  const { t, i18n } = useTranslation('status');
  const {
    status,
    isLoading,
    isRefreshing,
    error,
    refresh,
    checkedAtLabel,
    isStale,
  } = useSystemStatus();
  const [refreshAnnouncement, setRefreshAnnouncement] = useState({
    message: '',
    sequence: 0,
  });
  const previousRefreshing = useRef(isRefreshing);
  const lastRefreshAttemptRef = useRef(performance.now());
  const announceNextRefreshRef = useRef(false);
  const hasStatus = Boolean(status);
  const shownOverall = useMemo(() => (
    error || isStale
      ? { status: 'unknown', title: t('overall.fallback.title'), message: t('overall.fallback.message') }
      : overallPresentation(status?.overall, t)
  ), [error, isStale, status?.overall, t]);

  useEffect(() => {
    if (previousRefreshing.current && !isRefreshing) {
      if (announceNextRefreshRef.current && !error && hasStatus && shownOverall) {
        setRefreshAnnouncement((current) => ({
          message: t('overall.refreshAnnouncement', { title: shownOverall.title }),
          sequence: current.sequence + 1,
        }));
      }
      announceNextRefreshRef.current = false;
    }
    previousRefreshing.current = isRefreshing;
  }, [error, hasStatus, isRefreshing, shownOverall, t]);

  const requestRefresh = useCallback((announce = false) => {
    lastRefreshAttemptRef.current = performance.now();
    announceNextRefreshRef.current = announce;
    try {
      Promise.resolve(refresh()).catch(() => {});
    } catch {
      // The provider owns the safe error state shown by this page.
    }
  }, [refresh]);

  const handleManualRefresh = useCallback(() => {
    requestRefresh(true);
  }, [requestRefresh]);

  const refreshIfDue = useCallback(() => {
    if (document.visibilityState !== 'visible' || navigator.onLine === false) return;
    const now = performance.now();
    if (now - lastRefreshAttemptRef.current < AUTO_REFRESH_INTERVAL_MS) return;
    requestRefresh();
  }, [requestRefresh]);

  useEffect(() => {
    const refreshTimer = window.setInterval(refreshIfDue, AUTO_REFRESH_INTERVAL_MS);
    document.addEventListener('visibilitychange', refreshIfDue);
    window.addEventListener('online', refreshIfDue);

    return () => {
      window.clearInterval(refreshTimer);
      document.removeEventListener('visibilitychange', refreshIfDue);
      window.removeEventListener('online', refreshIfDue);
    };
  }, [refreshIfDue]);

  const capabilities = hasStatus ? capabilityItems(status, isStale, t) : [];
  const dependencies = hasStatus ? dependencyItems(status, isStale, t) : [];

  return (
    <div className="system-status-page">
      <header className="system-status-page__header">
        <div>
          <h1>{t('page.heading')}</h1>
          <p>{t('page.description')}</p>
        </div>
        <Button
          className="system-status-refresh"
          kind="tertiary"
          renderIcon={Renew}
          type="button"
          disabled={isLoading || isRefreshing}
          onClick={handleManualRefresh}
        >
          {error ? t('actions.retry') : t('actions.refresh')}
        </Button>
      </header>

      <section
        className={`system-status-overall system-status-overall--${shownOverall?.status || 'checking'}`}
        aria-labelledby="overall-status-heading"
      >
        {shownOverall ? (
          <>
            <StatusMark status={shownOverall.status} large />
            <div className="system-status-overall__copy">
              <h2 id="overall-status-heading">{shownOverall.title}</h2>
              <p>{shownOverall.message}</p>
              <div className="system-status-overall__timing">
                {checkedAtLabel && <span className="system-status-checked-at">{checkedAtLabel}</span>}
                {isRefreshing && (
                  <InlineLoading
                    aria-live="off"
                    description={t('refreshing')}
                    iconDescription={t('refreshing')}
                    status="active"
                  />
                )}
              </div>
              {isStale && (
                <p className="system-status-stale-note">
                  {t('stale')}
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="system-status-overall__loading">
            <h2 id="overall-status-heading">{t('overall.checking')}</h2>
            <InlineLoading
              aria-live="off"
              description={t('overall.checking')}
              iconDescription={t('overall.checking')}
              status="active"
            />
          </div>
        )}
      </section>

      <section className="system-status-capabilities" aria-labelledby="capabilities-heading">
        <h2 id="capabilities-heading">{t('capabilities.heading')}</h2>
        {hasStatus ? (
          <ul className="system-status-capability-grid" aria-label={t('capabilities.listLabel')}>
            {capabilities.map((capability) => (
              <li className="system-status-capability" key={capability.id}>
                <div className="system-status-capability__heading">
                  <h3>{capability.label}</h3>
                  <StatusMark status={capability.status} />
                </div>
                <p>{capability.message}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="system-status-capabilities__empty">
            {t('capabilities.empty')}
          </p>
        )}
      </section>

      <section className="system-status-technical" aria-label={t('technical.ariaLabel')}>
        <Accordion align="start" size="lg">
          <AccordionItem title={t('technical.title')}>
            {dependencies.length > 0 ? (
              <ul className="system-status-dependencies" aria-label={t('technical.listLabel')}>
                {dependencies.map((dependency) => {
                  const statusLabel = t(`statuses.${STATUS_PRESENTATION[dependency.status] ? dependency.status : 'unknown'}`);
                  return (
                    <li
                      className="system-status-dependency"
                      key={dependency.id}
                      aria-label={`${dependency.label}, ${statusLabel}`}
                    >
                      <div className="system-status-dependency__heading">
                        <h3>{dependency.label}</h3>
                        <StatusMark status={dependency.status} />
                      </div>
                      <div className="system-status-dependency__details">
                        <p>{dependencyMessage(dependency, t)}</p>
                        <DependencyProblem problem={dependency.problem} />
                        <p className="system-status-dependency__meta">
                          <span>{t(`evidence.${dependency.evidence}`, { defaultValue: t('evidence.unknown') })}</span>
                          <span>{dependencyTiming(dependency, t, i18n.resolvedLanguage)}</span>
                        </p>
                        {dependency.id === 'openllmetry' && (
                          <p className="system-status-dependency__note">
                            {t('technical.openllmetryNote')}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="system-status-technical__empty">
                {t('technical.empty')}
              </p>
            )}
          </AccordionItem>
        </Accordion>
      </section>

      <span className="system-status-sr-only" aria-live="polite" aria-atomic="true">
        {refreshAnnouncement.message && (
          <span key={refreshAnnouncement.sequence}>{refreshAnnouncement.message}</span>
        )}
      </span>
    </div>
  );
};

export default SystemStatus;
