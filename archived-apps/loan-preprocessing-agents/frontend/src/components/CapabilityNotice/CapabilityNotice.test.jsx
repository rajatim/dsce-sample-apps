import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { useSystemStatusMock } = vi.hoisted(() => ({ useSystemStatusMock: vi.fn() }));

vi.mock('../../contexts/useSystemStatus', () => ({ useSystemStatus: useSystemStatusMock }));

import CapabilityNotice from './CapabilityNotice';
import i18n from '../../i18n/config';

const setCapabilities = (capabilities, overrides = {}) => {
  useSystemStatusMock.mockReturnValue({
    status: { capabilities },
    isLoading: false,
    error: null,
    ...overrides,
  });
};

describe('CapabilityNotice', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
  });
  it('renders nothing when all requested capabilities are ready', () => {
    setCapabilities([{ id: 'submit_application', status: 'ready' }]);
    const { container } = render(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows only the highest-impact notice', () => {
    setCapabilities([
      { id: 'submit_application', status: 'limited', message: 'untrusted limited copy' },
      { id: 'process_documents', status: 'unavailable', message: 'untrusted unavailable copy' },
    ]);
    render(<CapabilityNotice capabilityIds={['submit_application', 'process_documents']} />);
    expect(screen.getByText('Document processing is currently unavailable.')).toBeVisible();
    expect(screen.queryByText('untrusted limited copy')).not.toBeInTheDocument();
    expect(screen.getByRole('status').className).toContain('--inline-notification--error');
  });

  it('uses warning for limited and error for not configured', () => {
    setCapabilities([{ id: 'submit_application', status: 'not_configured', message: 'Submission is not configured.' }]);
    const { rerender } = render(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(screen.getByRole('status').className).toContain('--inline-notification--error');

    setCapabilities([{ id: 'submit_application', status: 'limited', message: 'Submission may be delayed.' }]);
    rerender(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(screen.getByRole('status').className).toContain('--inline-notification--warning');
  });

  it.each([
    ['unknown', { status: { capabilities: [{ id: 'submit_application', status: 'unknown' }] } }],
    ['initial loading', { status: null, isLoading: true }],
    ['stale-only', { status: { stale: true, capabilities: [{ id: 'submit_application', status: 'ready' }] } }],
  ])('does not show an outage for %s state', (_label, state) => {
    useSystemStatusMock.mockReturnValue({ status: null, isLoading: false, error: null, ...state });
    const { container } = render(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('links to the demo status page and falls back to safe copy', () => {
    setCapabilities([{ id: 'process_documents', status: 'unavailable', message: 'PostgreSQL connection refused at 10.0.0.9' }]);
    render(<CapabilityNotice capabilityIds={['process_documents']} />);
    expect(screen.getByText('Document processing is currently unavailable.')).toBeVisible();
    const notification = screen.getByRole('status');
    const link = screen.getByRole('link', { name: 'View demo status' });
    expect(link).toHaveAttribute('href', '/status');
    expect(notification).not.toContainElement(link);
    expect(screen.queryByText(/PostgreSQL|10\.0\.0\.9/)).not.toBeInTheDocument();
  });

  it('suppresses notices when the relative checked label has become stale', () => {
    setCapabilities(
      [{ id: 'submit_application', status: 'unavailable', message: 'Do not display this.' }],
      { isStale: true },
    );
    const { container } = render(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('localizes safe capability copy without rendering backend details', async () => {
    await i18n.changeLanguage('zh-TW');
    setCapabilities([{ id: 'process_documents', status: 'unavailable', message: 'Private backend detail' }]);
    render(<CapabilityNotice capabilityIds={['process_documents']} />);
    expect(screen.getByText('文件處理目前無法使用。')).toBeVisible();
    expect(screen.getByRole('link', { name: '查看 Demo 狀態' })).toHaveAttribute('href', '/status');
    expect(screen.queryByText('Private backend detail')).not.toBeInTheDocument();
  });
});
