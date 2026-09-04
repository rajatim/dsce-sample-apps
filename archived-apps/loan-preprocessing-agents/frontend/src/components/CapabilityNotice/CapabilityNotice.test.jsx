import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { useSystemStatusMock } = vi.hoisted(() => ({ useSystemStatusMock: vi.fn() }));

vi.mock('../../contexts/useSystemStatus', () => ({ useSystemStatus: useSystemStatusMock }));
vi.mock('@carbon/react', () => ({
  InlineNotification: ({ kind, title, subtitle, children }) => (
    <div role="alert" data-kind={kind}>
      <span>{title}</span>
      <span>{subtitle}</span>
      {children}
    </div>
  ),
}));

import CapabilityNotice from './CapabilityNotice';

const setCapabilities = (capabilities, overrides = {}) => {
  useSystemStatusMock.mockReturnValue({
    status: { capabilities },
    isLoading: false,
    error: null,
    ...overrides,
  });
};

describe('CapabilityNotice', () => {
  it('renders nothing when all requested capabilities are ready', () => {
    setCapabilities([{ id: 'submit_application', status: 'ready' }]);
    const { container } = render(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows only the highest-impact notice', () => {
    setCapabilities([
      { id: 'submit_application', status: 'limited', message: 'Submission may be delayed.' },
      { id: 'process_documents', status: 'unavailable', message: 'Document processing is unavailable.' },
    ]);
    render(<CapabilityNotice capabilityIds={['submit_application', 'process_documents']} />);
    expect(screen.getByText('Document processing is unavailable.')).toBeVisible();
    expect(screen.queryByText('Submission may be delayed.')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveAttribute('data-kind', 'error');
  });

  it('uses warning for limited and error for not configured', () => {
    setCapabilities([{ id: 'submit_application', status: 'not_configured', message: 'Submission is not configured.' }]);
    const { rerender } = render(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(screen.getByRole('alert')).toHaveAttribute('data-kind', 'error');

    setCapabilities([{ id: 'submit_application', status: 'limited', message: 'Submission may be delayed.' }]);
    rerender(<CapabilityNotice capabilityIds={['submit_application']} />);
    expect(screen.getByRole('alert')).toHaveAttribute('data-kind', 'warning');
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
    setCapabilities([{ id: 'process_documents', status: 'unavailable', message: 'https://internal.example/raw-id' }]);
    render(<CapabilityNotice capabilityIds={['process_documents']} />);
    expect(screen.getByText('Document processing is currently unavailable.')).toBeVisible();
    expect(screen.getByRole('link', { name: 'View demo status' })).toHaveAttribute('href', '/status');
    expect(screen.queryByText(/internal\.example|raw-id/)).not.toBeInTheDocument();
  });
});
