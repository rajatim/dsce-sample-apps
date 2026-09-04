import React from 'react';
import { InlineNotification } from '@carbon/react';
import { useSystemStatus } from '../../contexts/useSystemStatus';

const SEVERITY = { limited: 1, not_configured: 2, unavailable: 3 };

const SAFE_COPY = {
  submit_application: {
    limited: 'Submission may be delayed.',
    not_configured: 'Submission is not configured for this demo.',
    unavailable: 'Submission is currently unavailable.',
  },
  process_documents: {
    limited: 'Document processing may be delayed.',
    not_configured: 'Document processing is not configured for this demo.',
    unavailable: 'Document processing is currently unavailable.',
  },
  generate_decision: {
    limited: 'Loan decisions may be delayed.',
    not_configured: 'Loan decisions are not configured for this demo.',
    unavailable: 'Loan decisions are currently unavailable.',
  },
  view_applications: {
    limited: 'Application history may be delayed.',
    not_configured: 'Application history is not configured for this demo.',
    unavailable: 'Application history is currently unavailable.',
  },
};

const CAPABILITY_LABELS = {
  submit_application: 'Submit an application',
  process_documents: 'Process documents',
  generate_decision: 'Generate a loan decision',
  view_applications: 'View applications',
};

const CapabilityNotice = ({ capabilityIds = [] }) => {
  const { status, isLoading, checkedAtLabel } = useSystemStatus();

  if (isLoading || !status || status.stale || checkedAtLabel === 'Status data is out of date') return null;

  const requested = status.capabilities?.filter((capability) => capabilityIds.includes(capability.id)) || [];
  const actionable = requested
    .filter((capability) => Object.hasOwn(SEVERITY, capability.status))
    .sort((left, right) => SEVERITY[right.status] - SEVERITY[left.status]);
  const capability = actionable[0];
  if (!capability) return null;

  const kind = capability.status === 'limited' ? 'warning' : 'error';
  const label = CAPABILITY_LABELS[capability.id] || 'This demo capability';
  const subtitle = SAFE_COPY[capability.id]?.[capability.status]
    || `${label} may be affected.`;

  return (
    <InlineNotification
      kind={kind}
      title={`${label} may be affected`}
      subtitle={subtitle}
      hideCloseButton
    >
      <a href="/status">View demo status</a>
    </InlineNotification>
  );
};

export default CapabilityNotice;
