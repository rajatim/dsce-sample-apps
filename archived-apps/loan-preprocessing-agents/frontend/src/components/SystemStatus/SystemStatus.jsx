import { useEffect, useRef, useState } from 'react';
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
import './SystemStatus.css';

const CAPABILITIES = [
  ['submit_application', 'Submit an application', 'Submission status could not be checked.'],
  ['process_documents', 'Process documents', 'Document processing status could not be checked.'],
  ['generate_decision', 'Generate a loan decision', 'Loan decision status could not be checked.'],
  ['view_applications', 'View applications', 'Application history status could not be checked.'],
];

const DEPENDENCIES = [
  ['loan_api', 'Loan API'],
  ['postgresql', 'PostgreSQL'],
  ['cos', 'IBM Cloud Object Storage'],
  ['watsonx_ai', 'watsonx.ai'],
  ['wxo', 'watsonx Orchestrate'],
  ['document_processing_agent', 'Document Processing Agent'],
  ['document_validation_agent', 'Document Validation Agent'],
  ['final_decision_agent', 'Final Decision Agent'],
  ['openllmetry', 'OpenLLMetry'],
];
const AGENT_DEPENDENCY_IDS = new Set([
  'document_processing_agent',
  'document_validation_agent',
  'final_decision_agent',
]);

const STATUS_PRESENTATION = {
  ready: { label: 'Ready', tag: 'green', Icon: CheckmarkFilled },
  limited: { label: 'Limited', tag: 'warm-gray', Icon: WarningAltFilled },
  unavailable: { label: 'Unavailable', tag: 'red', Icon: ErrorFilled },
  checking: { label: 'Checking', tag: 'blue', Icon: Renew },
  unknown: { label: 'Status unavailable', tag: 'gray', Icon: UnknownFilled },
  not_configured: { label: 'Not configured', tag: 'red', Icon: ErrorFilled },
};

const EVIDENCE_LABELS = {
  live_check: 'Live check',
  configured: 'Configured',
  recent_execution: 'Recent execution',
  not_verified: 'Not verified',
};

const formatTimestamp = (value) => {
  if (!value) return '';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
};

const StatusMark = ({ status, large = false }) => {
  const presentation = STATUS_PRESENTATION[status] || STATUS_PRESENTATION.unknown;
  const Icon = presentation.Icon;

  return (
    <span className={`system-status-mark system-status-mark--${status || 'unknown'}`}>
      <Icon size={large ? 32 : 20} aria-hidden="true" />
      <Tag size="sm" type={presentation.tag}>{presentation.label}</Tag>
    </span>
  );
};

const capabilityItems = (status, isStale) => CAPABILITIES.map(([id, label, fallbackMessage]) => {
  const capability = status?.capabilities.find((item) => item.id === id);
  return {
    id,
    label,
    status: isStale ? 'unknown' : capability?.status || 'unknown',
    message: isStale ? fallbackMessage : capability?.message || fallbackMessage,
  };
});

const dependencyItems = (status) => DEPENDENCIES.flatMap(([id, label]) => {
  const dependency = status?.dependencies.find((item) => item.id === id);
  return dependency ? [{ ...dependency, id, label }] : [];
});

const dependencyTiming = (dependency) => {
  if (AGENT_DEPENDENCY_IDS.has(dependency.id)) {
    const lastSuccess = Date.parse(dependency.last_success_at);
    const lastFailure = Date.parse(dependency.last_failure_at);
    const hasSuccess = Number.isFinite(lastSuccess);
    const hasFailure = Number.isFinite(lastFailure);
    if (hasFailure && (!hasSuccess || lastFailure >= lastSuccess)) {
      return `Last failed run ${formatTimestamp(dependency.last_failure_at)}`;
    }
    if (hasSuccess) {
      return `Last successful run ${formatTimestamp(dependency.last_success_at)}`;
    }
    return 'No recent run';
  }
  if (dependency.checked_at) {
    return `Checked at ${formatTimestamp(dependency.checked_at)}`;
  }
  if (dependency.evidence === 'recent_execution') return 'No recent run';
  return 'No recent check';
};

const SystemStatus = () => {
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

  useEffect(() => {
    if (previousRefreshing.current && !isRefreshing && !error && status) {
      setRefreshAnnouncement((current) => ({
        message: `Demo status refreshed. ${status.overall.title}.`,
        sequence: current.sequence + 1,
      }));
    }
    previousRefreshing.current = isRefreshing;
  }, [error, isRefreshing, status]);

  const handleRefresh = () => {
    try {
      Promise.resolve(refresh()).catch(() => {});
    } catch {
      // The provider owns the safe error state shown by this page.
    }
  };

  const hasStatus = Boolean(status);
  const shownOverall = error || isStale
    ? {
        status: 'unknown',
        title: 'Status unavailable',
        message: 'We could not check the demo status. You may still try the demo.',
    }
    : status?.overall;
  const capabilities = hasStatus ? capabilityItems(status, isStale) : [];
  const dependencies = hasStatus ? dependencyItems(status) : [];

  return (
    <div className="system-status-page">
      <header className="system-status-page__header">
        <div>
          <h1>Demo status</h1>
          <p>See which parts of the loan demo are available before you begin.</p>
        </div>
        <Button
          className="system-status-refresh"
          kind="tertiary"
          renderIcon={Renew}
          type="button"
          disabled={isLoading || isRefreshing}
          onClick={handleRefresh}
        >
          {error ? 'Retry' : 'Refresh'}
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
                    description="Checking latest status"
                    iconDescription="Checking latest status"
                    status="active"
                  />
                )}
              </div>
              {isStale && (
                <p className="system-status-stale-note">
                  Refresh before relying on these results.
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="system-status-overall__loading">
            <h2 id="overall-status-heading">Checking demo status</h2>
            <InlineLoading
              aria-live="off"
              description="Checking demo status"
              iconDescription="Checking demo status"
              status="active"
            />
          </div>
        )}
      </section>

      <section className="system-status-capabilities" aria-labelledby="capabilities-heading">
        <h2 id="capabilities-heading">What you can do now</h2>
        {hasStatus ? (
          <ul className="system-status-capability-grid" aria-label="Demo capabilities">
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
            Capability details will appear when the latest status is available.
          </p>
        )}
      </section>

      <section className="system-status-technical" aria-label="Technical status">
        <Accordion align="start" size="lg">
          <AccordionItem title="Technical details">
            {dependencies.length > 0 ? (
              <ul className="system-status-dependencies" aria-label="Technical dependencies">
                {dependencies.map((dependency) => {
                  const statusLabel = (
                    STATUS_PRESENTATION[dependency.status] || STATUS_PRESENTATION.unknown
                  ).label;
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
                        <p>{dependency.message}</p>
                        <p className="system-status-dependency__meta">
                          <span>{EVIDENCE_LABELS[dependency.evidence] || 'Not verified'}</span>
                          <span>{dependencyTiming(dependency)}</span>
                        </p>
                        {dependency.id === 'openllmetry' && (
                          <p className="system-status-dependency__note">
                            Does not affect demo availability.
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="system-status-technical__empty">
                Technical status is unavailable until the next successful check.
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
