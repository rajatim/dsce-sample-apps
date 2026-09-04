import React from 'react';
import { InlineNotification } from '@carbon/react';
import { useSystemStatus } from '../../contexts/useSystemStatus';

const SEVERITY = { limited: 1, not_configured: 2, unavailable: 3 };

const SAFE_COPY = {
  submit_application: 'Submission is currently unavailable.',
  process_documents: 'Document processing is currently unavailable.',
  generate_decision: 'Loan decisions are currently unavailable.',
  view_applications: 'Application history is currently unavailable.',
};

const CAPABILITY_LABELS = {
  submit_application: 'Submit an application',
  process_documents: 'Process documents',
  generate_decision: 'Generate a loan decision',
  view_applications: 'View applications',
};

const isSafeMessage = (message) => typeof message === 'string'
  && message.length <= 240
  && !/[\r\n]|https?:\/\/|www\.|\b(?:id|url|endpoint|api|token|trace|request)[-_ ]?(?:id|url)?\b/i.test(message);

const CapabilityNotice = ({ capabilityIds = [] }) => {
  const { status, isLoading } = useSystemStatus();

  if (isLoading || !status || status.stale) return null;

  const requested = status.capabilities?.filter((capability) => capabilityIds.includes(capability.id)) || [];
  const actionable = requested
    .filter((capability) => Object.hasOwn(SEVERITY, capability.status))
    .sort((left, right) => SEVERITY[right.status] - SEVERITY[left.status]);
  const capability = actionable[0];
  if (!capability) return null;

  const kind = capability.status === 'limited' ? 'warning' : 'error';
  const label = CAPABILITY_LABELS[capability.id] || 'This demo capability';
  const subtitle = isSafeMessage(capability.message)
    ? capability.message
    : SAFE_COPY[capability.id] || `${label} is currently unavailable.`;

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
