import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Button, InlineNotification, Loading, Tag } from '@carbon/react';
import { Renew } from '@carbon/react/icons';
import { useTranslation } from 'react-i18next';
import { authFetch } from '../../services/api';
import { buildApiUrl } from '../../services/apiBaseUrl';
import { formatDateTime } from '../../i18n/format';
import StructuredLogData from './StructuredLogData';
import './LogViewer.css';

const AGENT_STEPS = [
  {
    key: 'document_processing',
    translationKey: 'documentProcessing',
  },
  {
    key: 'document_validation',
    translationKey: 'documentValidation',
  },
  {
    key: 'final_decision',
    translationKey: 'finalDecision',
  },
];

const ACTIVE_STATUSES = new Set(['pending', 'processing', 'retrying']);

const RESULT_PRESENTATION = {
  passed: {
    translationKey: 'passed',
    tagType: 'green',
    tone: 'success',
  },
  rejected: {
    translationKey: 'rejected',
    tagType: 'red',
    tone: 'rejected',
  },
  'processing failed': {
    translationKey: 'processingFailed',
    tagType: 'red',
    tone: 'error',
  },
  pending: {
    translationKey: 'pending',
    tagType: 'blue',
    tone: 'active',
  },
  processing: {
    translationKey: 'processing',
    tagType: 'blue',
    tone: 'active',
  },
  retrying: {
    translationKey: 'retrying',
    tagType: 'purple',
    tone: 'warning',
  },
};

const FIELD_LABELS = new Set([
  'document_authenticity',
  'cross_validation',
  'age_verification',
  'overall_validation_summary',
  'applicant_age',
  'dob_consistency',
  'status',
  'details',
  'error',
]);

const normalizeStatus = (status) => status?.trim().toLowerCase() || 'unknown';

const statusPresentation = (status, t) => {
  const known = RESULT_PRESENTATION[normalizeStatus(status)];
  if (!known) {
    return {
      title: t('results.unknown.title'),
      description: t('results.unknown.description'),
      tag: status?.trim() || t('results.unknown.tag'),
      tagType: 'gray',
      tone: 'neutral',
    };
  }
  const prefix = `results.${known.translationKey}`;
  return {
    ...known,
    title: t(`${prefix}.title`),
    description: t(`${prefix}.description`),
    tag: t(`${prefix}.tag`),
  };
};

const isErrorResponse = (data) => {
  const value = typeof data === 'string' ? data : JSON.stringify(data || '');
  const normalized = value.toLowerCase();
  return normalized.includes('encountered an error')
    || normalized.includes('processing failed')
    || normalized.includes('please retry');
};

const eventMessage = (data) => {
  if (typeof data === 'string') return data;
  return typeof data?.message === 'string' ? data.message : '';
};

const agentKeyFromInvocation = (data) => {
  const value = eventMessage(data).toLowerCase();
  if (value.includes('document processor')) return 'document_processing';
  if (value.includes('document validator')) return 'document_validation';
  if (value.includes('final decision')) return 'final_decision';
  return null;
};

const sortLogs = (logs) => [...logs].sort((left, right) => {
  const leftTime = Date.parse(left.timestamp);
  const rightTime = Date.parse(right.timestamp);
  if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) return 0;
  return leftTime - rightTime;
});

const buildRuns = (logs) => {
  const runs = [];
  let currentRun = null;
  let currentAgent = null;

  sortLogs(logs).forEach((event) => {
    const invokedAgent = event.stage === 'invoke_agent'
      ? agentKeyFromInvocation(event.data)
      : null;

    if (
      invokedAgent === 'document_processing'
      && currentRun
      && currentRun.events.length > 0
    ) {
      runs.push(currentRun);
      currentRun = null;
      currentAgent = null;
    }

    if (!currentRun) {
      currentRun = { events: [] };
    }

    if (invokedAgent) {
      currentAgent = invokedAgent;
    }
    if (event.stage === 'final_continuation' || event.stage === 'demo_final_fallback') {
      currentAgent = 'final_decision';
    }

    currentRun.events.push({ ...event, agentKey: currentAgent });
  });

  if (currentRun?.events.length) {
    runs.push(currentRun);
  }

  return runs.map((run, index) => ({ ...run, number: index + 1 }));
};

const stepState = (stepKey, run, applicationStatus, isLatestRun) => {
  const events = run.events.filter((event) => event.agentKey === stepKey);
  if (!events.length) {
    return { key: 'not-started', translationKey: 'notStarted' };
  }

  const startedStepIndexes = AGENT_STEPS
    .map((step, index) => run.events.some((event) => event.agentKey === step.key) ? index : -1)
    .filter((index) => index >= 0);
  const stepIndex = AGENT_STEPS.findIndex((step) => step.key === stepKey);
  const lastStartedIndex = Math.max(...startedStepIndexes);
  const normalizedApplicationStatus = normalizeStatus(applicationStatus);
  const hasAgentError = events.some(
    (event) => event.stage === 'agent_response' && isErrorResponse(event.data)
  );
  const hasRetry = events.some((event) => event.stage === 'retry');
  const hasResponse = events.some((event) => event.stage === 'agent_response');
  const hasFallback = events.some((event) => event.stage === 'demo_final_fallback');
  const laterStepStarted = stepIndex < lastStartedIndex;

  if (hasAgentError) {
    return { key: 'failed', translationKey: 'failed' };
  }
  if (
    hasRetry
    && isLatestRun
    && normalizedApplicationStatus === 'retrying'
    && stepIndex === lastStartedIndex
  ) {
    return { key: 'retrying', translationKey: 'retrying' };
  }
  if (
    isLatestRun
    && normalizedApplicationStatus === 'processing failed'
    && stepIndex === lastStartedIndex
    && !hasFallback
  ) {
    return { key: 'failed', translationKey: 'failed' };
  }
  if (hasResponse || hasFallback || laterStepStarted) {
    return { key: 'complete', translationKey: 'complete' };
  }
  if (
    isLatestRun
    && ACTIVE_STATUSES.has(normalizedApplicationStatus)
    && stepIndex === lastStartedIndex
  ) {
    return { key: 'processing', translationKey: 'processing' };
  }
  return { key: 'stopped', translationKey: 'stopped' };
};

const parseValidationComments = (comments) => {
  if (!comments?.trim()) return [];

  const sections = [];
  let currentSection = null;
  const markdownField = /^\s*-\s+\*\*([^*]+)\*\*:\s*(.*)$/;

  comments.split(/\r?\n/).forEach((line) => {
    const match = line.match(markdownField);
    if (!match) {
      if (line.trim() && currentSection) {
        currentSection.value = `${currentSection.value || ''} ${line.trim()}`.trim();
      }
      return;
    }

    const [, key, value] = match;
    const isTopLevel = !/^\s/.test(line);
    if (isTopLevel) {
      currentSection = { key, value, fields: {} };
      sections.push(currentSection);
      return;
    }

    if (currentSection) {
      currentSection.fields[key] = value;
    }
  });

  return sections.length ? sections : [{ key: 'details', value: comments.trim(), fields: {} }];
};

const displayFieldLabel = (key, t) => (
  FIELD_LABELS.has(key) ? t(`validation.fieldLabels.${key}`) : key.replaceAll('_', ' ')
);

const validationTone = (status) => {
  const normalized = normalizeStatus(status);
  if (normalized === 'passed' || normalized === 'valid') return 'success';
  if (normalized === 'failed' || normalized === 'invalid') return 'error';
  return 'neutral';
};

const formatTimestamp = (timestamp, locale) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return formatDateTime(date, locale);
};

const eventTitle = (event, t) => {
  if (event.stage === 'invoke_agent') return eventMessage(event.data) || t('events.agentStarted');
  if (event.stage === 'tool_call') return t('events.toolCalled');
  if (event.stage === 'tool_response') return t('events.toolReturned');
  if (event.stage === 'retry') return event.data?.attempt
    ? t('events.retryAttempt', { attempt: event.data.attempt })
    : t('events.retryRequested');
  if (event.stage === 'final_continuation') return t('events.finalRequestedAgain');
  if (event.stage === 'demo_final_fallback') return t('events.fallbackCompleted');
  if (event.stage === 'agent_response' && isErrorResponse(event.data)) return t('events.agentError');
  if (event.stage === 'agent_response') return t('events.agentResponse');
  return t('events.streamUpdate');
};

const ValidationFindings = ({ comments }) => {
  const { t } = useTranslation('logs');
  const sections = parseValidationComments(comments);
  if (!sections.length) return null;

  return (
    <section className="validation-findings" aria-labelledby="validation-findings-title">
      <h3 id="validation-findings-title">{t('validation.heading')}</h3>
      <div className="validation-findings-list">
        {sections.map((section) => {
          const status = section.fields.status;
          const detail = section.fields.details || section.value;
          const metadata = Object.entries(section.fields).filter(
            ([key]) => !['status', 'details'].includes(key)
          );
          return (
            <article
              className={`validation-finding validation-finding--${validationTone(status)}`}
              key={section.key}
            >
              <div className="validation-finding-heading">
                <h4>{displayFieldLabel(section.key, t)}</h4>
                {status && <span className="validation-finding-status">{status}</span>}
              </div>
              {detail && <p>{detail}</p>}
              {metadata.length > 0 && (
                <dl className="validation-finding-metadata">
                  {metadata.map(([key, value]) => (
                    <React.Fragment key={key}>
                      <dt>{displayFieldLabel(key, t)}</dt>
                      <dd>{value || '—'}</dd>
                    </React.Fragment>
                  ))}
                </dl>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
};

const ProcessingRun = ({ run, applicationStatus, isLatest, showRunLabel }) => {
  const { t } = useTranslation('logs');
  return (
    <article className="processing-run">
      {showRunLabel && (
        <div className="processing-run-heading">
          <h4>{t('runs.label', { number: run.number })}</h4>
          {isLatest && <span>{t('runs.latest')}</span>}
        </div>
      )}
      <ol className="agent-timeline">
        {AGENT_STEPS.map((step) => {
          const state = stepState(step.key, run, applicationStatus, isLatest);
          const name = t(`agents.${step.translationKey}.name`);
          const stateLabel = t(`stepStates.${state.translationKey}`);
          return (
            <li
              className={`agent-step agent-step--${state.key}`}
              aria-label={`${name}: ${stateLabel}`}
              key={step.key}
            >
              <span className="agent-step-marker" aria-hidden="true" />
              <div className="agent-step-content">
                <div className="agent-step-heading">
                  <h4>{name}</h4>
                  <span className="agent-step-status">{stateLabel}</span>
                </div>
                <p>{t(`agents.${step.translationKey}.description`)}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </article>
  );
};

const TechnicalEventData = ({ data }) => {
  const { t } = useTranslation('logs');
  const contentId = useId();
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="technical-event-data">
      <Button
        className="technical-event-data__toggle"
        kind="ghost"
        size="sm"
        type="button"
        aria-controls={contentId}
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((expanded) => !expanded)}
      >
        {t(isExpanded ? 'technical.hideRaw' : 'technical.showRaw')}
      </Button>
      {isExpanded && (
        <div id={contentId}>
          <StructuredLogData data={data} />
        </div>
      )}
    </div>
  );
};

const TechnicalDetails = ({ logs }) => {
  const { t, i18n } = useTranslation('logs');
  return (
    <details className="technical-details">
      <summary>
        <span>{t('technical.heading')}</span>
        <span className="technical-details-count">{t('technical.eventCount', { count: logs.length })}</span>
      </summary>
      <div className="technical-event-list">
        {logs.map((event, index) => (
          <article className={`technical-event technical-event--${event.stage}`} key={`${event.timestamp}-${index}`}>
            <div className="technical-event-heading">
              <div>
                <span className="technical-event-type">
                  {t(`eventTypes.${event.stage}`, { defaultValue: event.stage.replaceAll('_', ' ') })}
                </span>
                <h4>{eventTitle(event, t)}</h4>
              </div>
              <time dateTime={event.timestamp}>{formatTimestamp(event.timestamp, i18n.resolvedLanguage)}</time>
            </div>
            {event.stage !== 'invoke_agent' && <TechnicalEventData data={event.data} />}
          </article>
        ))}
      </div>
    </details>
  );
};

const httpStatusLabel = (status) => {
  const labels = {
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    429: 'Too Many Requests',
    500: 'Internal Server Error',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
  };
  return status ? `${status}${labels[status] ? ` ${labels[status]}` : ''}` : '—';
};

const ProcessingFailureSummary = ({ failure }) => {
  const { t } = useTranslation('logs');
  const knownCategories = new Set([
    'provider_quota',
    'provider_authorization',
    'provider_rate_limit',
    'provider_unavailable',
    'timeout',
    'unknown',
  ]);
  const knownStages = new Set([
    'document_processing_agent',
    'document_validation_agent',
    'final_decision_agent',
    'agent_workflow',
  ]);
  const knownActions = new Set([
    'check_service_configuration',
    'retry_later',
    'review_technical_details',
  ]);
  const category = knownCategories.has(failure.category) ? failure.category : 'unknown';
  const service = failure.service === 'watsonx_ai' ? 'watsonx_ai' : 'agent_workflow';
  const stage = knownStages.has(failure.stage) ? failure.stage : 'agent_workflow';
  const action = knownActions.has(failure.action)
    ? failure.action
    : 'review_technical_details';

  const copyTraceId = () => {
    if (failure.trace_id && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(failure.trace_id);
    }
  };

  return (
    <section className="processing-problem" aria-labelledby="processing-problem-title">
      <div className="processing-problem__summary">
        <p className="processing-problem__label">{t('failure.label')}</p>
        <h3 id="processing-problem-title">{t(`failure.categories.${category}.title`)}</h3>
        <p>{t(`failure.categories.${category}.description`)}</p>
        {category === 'provider_quota' && (
          <p className="processing-problem__clarification">
            {t('failure.categories.provider_quota.clarification')}
          </p>
        )}
      </div>

      <div className="processing-problem__action">
        <h4>{t('failure.actionHeading')}</h4>
        <p>{t(`failure.actions.${action}`)}</p>
        {!failure.retryable_now && <p>{t('failure.retryAfterFix')}</p>}
        {failure.documentation_url && (
          <a href={failure.documentation_url} target="_blank" rel="noreferrer">
            {t('failure.documentation')}
          </a>
        )}
      </div>

      <dl className="processing-problem__facts">
        <div>
          <dt>{t('failure.fields.stage')}</dt>
          <dd>{t(`failure.stages.${stage}`)}</dd>
        </div>
        <div>
          <dt>{t('failure.fields.service')}</dt>
          <dd>{t(`failure.services.${service}`)}</dd>
        </div>
        <div>
          <dt>{t('failure.fields.code')}</dt>
          <dd><code>{failure.provider_code}</code></dd>
        </div>
        <div>
          <dt>{t('failure.fields.httpStatus')}</dt>
          <dd><code>{httpStatusLabel(failure.http_status)}</code></dd>
        </div>
        {failure.trace_id && (
          <div className="processing-problem__trace">
            <dt>{t('failure.fields.traceId')}</dt>
            <dd>
              <code>{failure.trace_id}</code>
              <Button
                kind="ghost"
                size="sm"
                type="button"
                aria-label={t('failure.copyTrace')}
                onClick={copyTraceId}
              >
                {t('failure.copy')}
              </Button>
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
};

const LogViewer = ({ application, appId, onApplicationChange }) => {
  const { t } = useTranslation('logs');
  const initialApplication = application || { app_id_str: appId, status: '' };
  const resolvedAppId = initialApplication.app_id_str || appId;
  const fetchInFlightRef = useRef(null);
  const [currentApplication, setCurrentApplication] = useState(initialApplication);
  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [isRetrying, setIsRetrying] = useState(false);
  const result = statusPresentation(currentApplication.status, t);
  const processingFailure = currentApplication.processing_failure;
  const runs = useMemo(() => buildRuns(logs), [logs]);

  const updateApplication = useCallback((nextApplication) => {
    if (!nextApplication?.app_id_str) return;
    setCurrentApplication(nextApplication);
    onApplicationChange?.(nextApplication);
  }, [onApplicationChange]);

  const fetchDetails = useCallback((showLoading = false) => {
    if (fetchInFlightRef.current) {
      return fetchInFlightRef.current;
    }
    if (showLoading) {
      setIsLoading(true);
    }
    setError('');

    const request = (async () => {
      try {
        const [applicationResponse, logsResponse] = await Promise.all([
          authFetch(buildApiUrl(`/applications/${resolvedAppId}`)),
          authFetch(buildApiUrl(`/get_logs/${resolvedAppId}`)),
        ]);
        if (!applicationResponse.ok || !logsResponse.ok) {
          throw new Error('processing.fetchError');
        }

        const [applicationData, logsData] = await Promise.all([
          applicationResponse.json(),
          logsResponse.json(),
        ]);
        updateApplication(applicationData);
        setLogs(sortLogs(Array.isArray(logsData.logs) ? logsData.logs : []));
      } catch (fetchError) {
        setError(fetchError.message);
      } finally {
        setIsLoading(false);
      }
    })();

    fetchInFlightRef.current = request;
    request.finally(() => {
      if (fetchInFlightRef.current === request) {
        fetchInFlightRef.current = null;
      }
    });
    return request;
  }, [resolvedAppId, updateApplication]);

  useEffect(() => {
    fetchDetails(true);
  }, [fetchDetails]);

  useEffect(() => {
    if (!ACTIVE_STATUSES.has(normalizeStatus(currentApplication.status))) {
      return undefined;
    }

    let cancelled = false;
    let pollingTimer;
    const poll = async () => {
      await fetchDetails();
      if (!cancelled) {
        pollingTimer = window.setTimeout(poll, 5000);
      }
    };
    pollingTimer = window.setTimeout(poll, 5000);

    return () => {
      cancelled = true;
      window.clearTimeout(pollingTimer);
    };
  }, [currentApplication.status, fetchDetails]);

  const retryProcessing = async () => {
    setIsRetrying(true);
    setActionError('');
    try {
      const response = await authFetch(
        buildApiUrl(`/applications/${resolvedAppId}/retry`),
        { method: 'POST' }
      );
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'notifications.retryFallback');
      }
      updateApplication(await response.json());
      await fetchDetails();
    } catch (retryError) {
      setActionError(retryError.message);
    } finally {
      setIsRetrying(false);
    }
  };

  return (
    <div className="log-viewer-panel">
      <header className="log-viewer-header">
        <div>
          <p className="log-viewer-eyebrow">{t('header.eyebrow')}</p>
          <h2>{t('header.title')}</h2>
          <code>{resolvedAppId}</code>
        </div>
        <Button
          kind="ghost"
          size="sm"
          onClick={() => fetchDetails(true)}
          renderIcon={Renew}
          iconDescription={t('header.refreshDescription')}
        >
          {t('header.refresh')}
        </Button>
      </header>

      <div className="log-viewer-content">
        <section className={`result-summary result-summary--${result.tone}`} aria-labelledby="result-summary-title">
          <div className="result-summary-copy">
            <p>{t('result.current')}</p>
            <h3 id="result-summary-title">{result.title}</h3>
            <p>{result.description}</p>
          </div>
          <div className="result-summary-actions">
            <Tag type={result.tagType}>{result.tag}</Tag>
            {normalizeStatus(currentApplication.status) === 'processing failed' && (
              <Button
                kind="secondary"
                size="sm"
                disabled={isRetrying || isLoading}
                onClick={retryProcessing}
              >
                {isRetrying ? t('actions.retrying') : t('actions.retry')}
              </Button>
            )}
          </div>
        </section>

        {actionError && (
          <InlineNotification
            kind="error"
            title={t('notifications.retryUnavailable')}
            subtitle={actionError === 'notifications.retryFallback' ? t(actionError) : actionError}
            hideCloseButton
          />
        )}

        {processingFailure && <ProcessingFailureSummary failure={processingFailure} />}
        {!processingFailure && (
          <ValidationFindings comments={currentApplication.validation_comments} />
        )}

        <section className="processing-history" aria-labelledby="processing-history-title">
          <div className="section-heading">
            <div>
              <h3 id="processing-history-title">{t('processing.heading')}</h3>
              <p>{t('processing.description')}</p>
            </div>
          </div>

          {isLoading && (
            <div className="processing-state">
              <Loading small withOverlay={false} description={t('processing.loading')} />
            </div>
          )}
          {error && (
            <InlineNotification
              kind="error"
              title={t('processing.errorTitle')}
              subtitle={error === 'processing.fetchError' ? t(error) : error}
              hideCloseButton
            />
          )}
          {!isLoading && !error && runs.length === 0 && (
            <div className="processing-empty-state">
              <h4>{t('processing.emptyHeading')}</h4>
              <p>{t('processing.emptyDescription')}</p>
            </div>
          )}
          {!isLoading && !error && runs.length > 0 && (
            <div className="processing-runs">
              {[...runs].reverse().map((run) => (
                <ProcessingRun
                  key={run.number}
                  run={run}
                  applicationStatus={currentApplication.status}
                  isLatest={run.number === runs.length}
                  showRunLabel={runs.length > 1}
                />
              ))}
            </div>
          )}
        </section>

        {!isLoading && !error && logs.length > 0 && <TechnicalDetails logs={logs} />}
      </div>
    </div>
  );
};

export default LogViewer;
