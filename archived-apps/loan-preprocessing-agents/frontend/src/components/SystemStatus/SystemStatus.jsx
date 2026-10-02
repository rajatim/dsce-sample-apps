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

const DEPENDENCIES = ['loan_api', 'postgresql', 'cos', 'watsonx_ai', 'wxo', 'document_processing_agent', 'document_validation_agent', 'final_decision_agent'];
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

const capabilityItems = (status, isStale, t, isCapabilityStale) => CAPABILITIES.map((id) => {
  const capability = status?.capabilities.find((item) => item.id === id);
  const outdated = capability && isCapabilityStale ? isCapabilityStale(capability) : isStale;
  const itemStatus = outdated ? 'unknown' : capability?.status || 'unknown';
  const fallbackMessage = t(`capabilities.fallbacks.${id}`);
  const knownMessage = ['ready', 'limited', 'unavailable', 'not_configured'].includes(itemStatus);
  const quotaBlocked = capability?.problem?.provider_code === 'token_quota_reached';
  return {
    id,
    label: t(`capabilities.labels.${id}`),
    status: itemStatus,
    message: !outdated && quotaBlocked
      ? t(`capabilities.problemMessages.provider_quota.${id}`, { defaultValue: fallbackMessage })
      : outdated
      ? fallbackMessage
      : knownMessage
        ? t(`capabilities.messages.${id}.${itemStatus}`)
        : capability?.message || fallbackMessage,
    problem: outdated ? null : capability?.problem,
  };
});

const dependencyItems = (status, isStale, t, isDependencyStale) => DEPENDENCIES.flatMap((id) => {
  const dependency = status?.dependencies.find((item) => item.id === id);
  return dependency ? [{
    ...dependency,
    id,
    label: t(`dependencies.${id}`),
    status: dependency.status,
    stale: isDependencyStale ? isDependencyStale(dependency) : isStale,
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
  if (dependency.problem?.blocked_by) return t('diagnostics.blocked', { service: t(`dependencies.${dependency.problem.blocked_by}`) });
  if (dependency.problem?.code) return t(`diagnostics.codes.${dependency.problem.code}`);
  if (dependency.problem?.provider_code === 'token_quota_reached') {
    return t('problems.provider_quota.dependencyMessage');
  }
  if (!STATUS_PRESENTATION[dependency.status]) return dependency.message;
  const group = AGENT_DEPENDENCY_IDS.has(dependency.id)
    ? 'agent'
    : 'service';
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
      {problem.code && <>
        <div><dt>{t('diagnostics.stage')}</dt><dd>{t(`diagnostics.stages.${problem.stage}`)}</dd></div>
        <div><dt>{t('diagnostics.providerMessage')}</dt><dd>{problem.provider_message || t('diagnostics.messageUnavailable')}</dd></div>
        <div><dt>{t('diagnostics.action')}</dt><dd>{t(`diagnostics.actions.${problem.action}`)}</dd></div>
      </>}
      <div>
        <dt>{t('problems.fields.code')}</dt>
        <dd><code>{problem.provider_code || problem.code || t('diagnostics.notSupplied')}</code></dd>
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
    checkDependency,
    isDependencyStale,
    isCapabilityStale,
    isChecking = () => false,
    checkError = () => '',
    checkOutcome = () => null,
    refreshOutcome,
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

  const capabilities = hasStatus ? capabilityItems(status, isStale, t, isCapabilityStale) : [];
  const dependencies = hasStatus ? dependencyItems(status, isStale, t, isDependencyStale) : [];

  const handleDependencyCheck = async (id) => {
    try {
      const result = await checkDependency(id);
      const message = result?.refresh?.result === 'cooldown'
        ? t('diagnostics.cooldown', { count: result.refresh.retry_after_seconds })
        : t('diagnostics.completed', { service: t(`dependencies.${id}`) });
      setRefreshAnnouncement((current) => ({ message, sequence: current.sequence + 1 }));
    } catch {
      // The provider keeps the prior result and exposes a safe error for this group.
    }
  };

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

      {refreshOutcome?.result === 'cooldown' && <p className="system-status-check-note">{t('diagnostics.cooldown', { count: refreshOutcome.retry_after_seconds })}</p>}
      {error && <p role="alert" className="system-status-check-note">{t('diagnostics.requestFailed')}</p>}
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
                      <div>
                        <div className="system-status-dependency__heading">
                          <h3>{dependency.label}</h3>
                          <StatusMark status={dependency.status} />
                        </div>
                        <Button kind="tertiary" size="sm" className="system-status-row-check"
                          aria-label={t('diagnostics.checkNamed', { service: dependency.label })}
                          disabled={isLoading || isChecking(dependency.id)}
                          onClick={() => handleDependencyCheck(dependency.id)}>
                          {isChecking(dependency.id) ? t('diagnostics.checking') : t('diagnostics.checkNow')}
                        </Button>
                      </div>
                      <div className="system-status-dependency__details">
                        {dependency.stale && <p className="system-status-stale-note">{t('diagnostics.outdated')}</p>}
                        <p>{dependencyMessage(dependency, t)}</p>
                        <p className="system-status-check-note">{t(`diagnostics.kinds.${dependency.check_kind || (AGENT_DEPENDENCY_IDS.has(dependency.id) || dependency.id === 'wxo' ? 'agent_registration' : 'metadata')}`)}</p>
                        {(AGENT_DEPENDENCY_IDS.has(dependency.id) || dependency.id === 'wxo') && <p className="system-status-check-note">{t('diagnostics.wxoGroup')}</p>}
                        {checkError(dependency.id) && <p role="alert">{t('diagnostics.requestFailed')}</p>}
                        {checkOutcome(dependency.id)?.result === 'cooldown' && <p role="status">{t('diagnostics.cooldown', { count: checkOutcome(dependency.id).retry_after_seconds })}</p>}
                        <DependencyProblem problem={dependency.problem} />
                        <p className="system-status-dependency__meta">
                          <span>{t(`evidence.${dependency.evidence}`, { defaultValue: t('evidence.unknown') })}</span>
                          <span>{dependency.checked_at ? t('timing.checkedAt', { time: formatDateTime(dependency.checked_at, i18n.resolvedLanguage) }) : t('timing.noRecentCheck')}</span>
                        </p>
                        {AGENT_DEPENDENCY_IDS.has(dependency.id) && (
                          <div className="system-status-dependency__note">
                            <p>{t('diagnostics.lastExecution')}</p>
                            <p>{dependencyTiming(dependency, t, i18n.resolvedLanguage)}</p>
                            <p className="system-status-check-note">{t('diagnostics.executionNote')}</p>
                          </div>
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
