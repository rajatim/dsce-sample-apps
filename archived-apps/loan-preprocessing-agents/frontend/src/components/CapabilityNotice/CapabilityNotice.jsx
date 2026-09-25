import React from 'react';
import { InlineNotification } from '@carbon/react';
import { useTranslation } from 'react-i18next';
import { useSystemStatus } from '../../contexts/useSystemStatus';

const SEVERITY = { limited: 1, not_configured: 2, unavailable: 3 };

const CapabilityNotice = ({ capabilityIds = [] }) => {
  const { t } = useTranslation('common');
  const { status, isLoading, isStale } = useSystemStatus();

  if (isLoading || !status || status.stale || isStale) return null;

  const requested = status.capabilities?.filter((capability) => capabilityIds.includes(capability.id)) || [];
  const actionable = requested
    .filter((capability) => Object.hasOwn(SEVERITY, capability.status))
    .sort((left, right) => SEVERITY[right.status] - SEVERITY[left.status]);
  const capability = actionable[0];
  if (!capability) return null;

  const kind = capability.status === 'limited' ? 'warning' : 'error';
  const label = t(`capabilityNotice.labels.${capability.id}`, {
    defaultValue: t('capabilityNotice.labels.fallback'),
  });
  const subtitle = t(`capabilityNotice.messages.${capability.id}.${capability.status}`, {
    defaultValue: t('capabilityNotice.fallback', { label }),
  });

  return (
    <>
      <InlineNotification
        kind={kind}
        title={t('capabilityNotice.title', { label })}
        subtitle={subtitle}
        hideCloseButton
      />
      <a href="/status">{t('capabilityNotice.viewStatus')}</a>
    </>
  );
};

export default CapabilityNotice;
