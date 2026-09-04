import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, InlineNotification, Loading, Tag } from '@carbon/react';
import { Renew } from '@carbon/react/icons';
import { authFetch } from '../../services/api';
import { buildApiUrl } from '../../services/apiBaseUrl';
import './LogViewer.css';

const AGENT_STEPS = [
  {
    key: 'document_processing',
    name: 'Document processing',
    description: 'Classifies each document and extracts the application fields.',
  },
  {
    key: 'document_validation',
    name: 'Document validation',
    description: 'Checks authenticity, completeness, expiry, and document risk.',
  },
  {
    key: 'final_decision',
    name: 'Final decision',
    description: 'Cross-checks the application and returns the validation result.',
  },
];

const ACTIVE_STATUSES = new Set(['pending', 'processing', 'retrying']);

const RESULT_PRESENTATION = {
  passed: {
    title: 'Validation passed',
    description: 'The application completed all required validation checks.',
    tag: 'Passed',
    tagType: 'green',
    tone: 'success',
  },
  rejected: {
    title: 'Application rejected',
    description: 'The agents completed their review and found validation issues.',
    tag: 'Rejected',
    tagType: 'red',
    tone: 'rejected',
  },
  'processing failed': {
    title: 'Processing failed',
    description: 'The agent workflow stopped before a final decision was produced.',
    tag: 'Failed',
    tagType: 'red',
    tone: 'error',
  },
  pending: {
    title: 'Waiting to start',
    description: 'The application is queued for agent processing.',
    tag: 'Pending',
    tagType: 'blue',
    tone: 'active',
  },
  processing: {
    title: 'Processing application',
    description: 'The agents are reviewing the application and its documents.',
    tag: 'Processing',
    tagType: 'blue',
    tone: 'active',
  },
  retrying: {
    title: 'Temporary interruption',
    description: 'The workflow is retrying an agent request automatically.',
    tag: 'Retrying',
    tagType: 'purple',
    tone: 'warning',
  },
};

const FIELD_LABELS = {
  document_authenticity: 'Document authenticity',
  cross_validation: 'Cross-document validation',
  age_verification: 'Age verification',
  overall_validation_summary: 'Overall summary',
  applicant_age: 'Applicant age',
  dob_consistency: 'Date of birth consistency',
  status: 'Status',
  details: 'Details',
  error: 'Error',
};

const normalizeStatus = (status) => status?.trim().toLowerCase() || 'unknown';

const statusPresentation = (status) => RESULT_PRESENTATION[normalizeStatus(status)] || {
  title: 'Application status',
  description: 'Review the available application and processing information below.',
  tag: status?.trim() || 'Unknown',
  tagType: 'gray',
  tone: 'neutral',
};

const isErrorResponse = (data) => {
  const value = typeof data === 'string' ? data : JSON.stringify(data || '');
  const normalized = value.toLowerCase();
  return normalized.includes('encountered an error')
    || normalized.includes('processing failed')
    || normalized.includes('please retry');
};

const agentKeyFromInvocation = (data) => {
  const value = String(data || '').toLowerCase();
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
    return { key: 'not-started', label: 'Not started' };
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
    return { key: 'failed', label: 'Failed' };
  }
  if (
    hasRetry
    && isLatestRun
    && normalizedApplicationStatus === 'retrying'
    && stepIndex === lastStartedIndex
  ) {
    return { key: 'retrying', label: 'Retrying' };
  }
  if (
    isLatestRun
    && normalizedApplicationStatus === 'processing failed'
    && stepIndex === lastStartedIndex
    && !hasFallback
  ) {
    return { key: 'failed', label: 'Failed' };
  }
  if (hasResponse || hasFallback || laterStepStarted) {
    return { key: 'complete', label: 'Complete' };
  }
  if (
    isLatestRun
    && ACTIVE_STATUSES.has(normalizedApplicationStatus)
    && stepIndex === lastStartedIndex
  ) {
    return { key: 'processing', label: 'Processing' };
  }
  return { key: 'stopped', label: 'Stopped' };
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

const displayFieldLabel = (key) => FIELD_LABELS[key] || key.replaceAll('_', ' ');

const validationTone = (status) => {
  const normalized = normalizeStatus(status);
  if (normalized === 'passed' || normalized === 'valid') return 'success';
  if (normalized === 'failed' || normalized === 'invalid') return 'error';
  return 'neutral';
};

const formatTimestamp = (timestamp) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date);
};

const formatLogData = (data) => {
  if (typeof data !== 'string') {
    return JSON.stringify(data, null, 2);
  }

  const fencedJson = data.match(/```(?:json)?\s*([\s\S]*?)```/i);
  let candidate = (fencedJson?.[1] || data).trim();

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const parsed = JSON.parse(candidate);
      if (typeof parsed === 'string') {
        candidate = parsed;
      } else {
        return JSON.stringify(parsed, null, 2);
      }
    } catch {
      return candidate;
    }
  }
  return candidate;
};

const eventTitle = (event) => {
  if (event.stage === 'invoke_agent') return String(event.data || 'Agent started');
  if (event.stage === 'tool_call') return 'Tool called';
  if (event.stage === 'tool_response') return 'Tool returned data';
  if (event.stage === 'retry') return `Agent retry requested${event.data?.attempt ? ` · attempt ${event.data.attempt}` : ''}`;
  if (event.stage === 'final_continuation') return 'Final decision response requested again';
  if (event.stage === 'demo_final_fallback') return 'POC fallback completed the decision';
  if (event.stage === 'agent_response' && isErrorResponse(event.data)) return 'Agent reported an error';
  if (event.stage === 'agent_response') return 'Agent returned a response';
  return 'Agent stream update';
};

const ValidationFindings = ({ comments }) => {
  const sections = parseValidationComments(comments);
  if (!sections.length) return null;

  return (
    <section className="validation-findings" aria-labelledby="validation-findings-title">
      <h3 id="validation-findings-title">Validation findings</h3>
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
                <h4>{displayFieldLabel(section.key)}</h4>
                {status && <span className="validation-finding-status">{status}</span>}
              </div>
              {detail && <p>{detail}</p>}
              {metadata.length > 0 && (
                <dl className="validation-finding-metadata">
                  {metadata.map(([key, value]) => (
                    <React.Fragment key={key}>
                      <dt>{displayFieldLabel(key)}</dt>
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

const ProcessingRun = ({ run, applicationStatus, isLatest, showRunLabel }) => (
  <article className="processing-run">
    {showRunLabel && (
      <div className="processing-run-heading">
        <h4>Run {run.number}</h4>
        {isLatest && <span>Latest</span>}
      </div>
    )}
    <ol className="agent-timeline">
      {AGENT_STEPS.map((step) => {
        const state = stepState(step.key, run, applicationStatus, isLatest);
        return (
          <li
            className={`agent-step agent-step--${state.key}`}
            aria-label={`${step.name}: ${state.label}`}
            key={step.key}
          >
            <span className="agent-step-marker" aria-hidden="true" />
            <div className="agent-step-content">
              <div className="agent-step-heading">
                <h4>{step.name}</h4>
                <span className="agent-step-status">{state.label}</span>
              </div>
              <p>{step.description}</p>
            </div>
          </li>
        );
      })}
    </ol>
  </article>
);

const TechnicalDetails = ({ logs }) => (
  <details className="technical-details">
    <summary>
      <span>Technical details</span>
      <span className="technical-details-count">{logs.length} events</span>
    </summary>
    <div className="technical-event-list">
      {logs.map((event, index) => (
        <article className={`technical-event technical-event--${event.stage}`} key={`${event.timestamp}-${index}`}>
          <div className="technical-event-heading">
            <div>
              <span className="technical-event-type">{event.stage.replaceAll('_', ' ')}</span>
              <h4>{eventTitle(event)}</h4>
            </div>
            <time dateTime={event.timestamp}>{formatTimestamp(event.timestamp)}</time>
          </div>
          {event.stage !== 'invoke_agent' && <pre>{formatLogData(event.data)}</pre>}
        </article>
      ))}
    </div>
  </details>
);

const LogViewer = ({ application, appId, onApplicationChange }) => {
  const initialApplication = application || { app_id_str: appId, status: '' };
  const resolvedAppId = initialApplication.app_id_str || appId;
  const fetchInFlightRef = useRef(null);
  const [currentApplication, setCurrentApplication] = useState(initialApplication);
  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [isRetrying, setIsRetrying] = useState(false);
  const result = statusPresentation(currentApplication.status);
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
          throw new Error('Failed to fetch processing details.');
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
        throw new Error(data.detail || 'The application could not be retried.');
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
          <p className="log-viewer-eyebrow">Application details</p>
          <h2>Loan application</h2>
          <code>{resolvedAppId}</code>
        </div>
        <Button
          kind="ghost"
          size="sm"
          onClick={() => fetchDetails(true)}
          renderIcon={Renew}
          iconDescription="Refresh processing details"
        >
          Refresh
        </Button>
      </header>

      <div className="log-viewer-content">
        <section className={`result-summary result-summary--${result.tone}`} aria-labelledby="result-summary-title">
          <div className="result-summary-copy">
            <p>Current result</p>
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
                {isRetrying ? 'Starting retry…' : 'Retry processing'}
              </Button>
            )}
          </div>
        </section>

        {actionError && (
          <InlineNotification
            kind="error"
            title="Retry unavailable"
            subtitle={actionError}
            hideCloseButton
          />
        )}

        <ValidationFindings comments={currentApplication.validation_comments} />

        <section className="processing-history" aria-labelledby="processing-history-title">
          <div className="section-heading">
            <div>
              <h3 id="processing-history-title">Agent processing</h3>
              <p>Three agents review the documents and produce the final result.</p>
            </div>
          </div>

          {isLoading && (
            <div className="processing-state">
              <Loading small withOverlay={false} description="Loading processing history" />
            </div>
          )}
          {error && (
            <InlineNotification
              kind="error"
              title="Processing history unavailable"
              subtitle={error}
              hideCloseButton
            />
          )}
          {!isLoading && !error && runs.length === 0 && (
            <div className="processing-empty-state">
              <h4>No processing history yet</h4>
              <p>The agent timeline will appear here after processing begins.</p>
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
