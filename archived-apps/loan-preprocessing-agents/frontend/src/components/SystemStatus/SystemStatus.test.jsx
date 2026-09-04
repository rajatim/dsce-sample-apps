import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { useSystemStatusMock } = vi.hoisted(() => ({ useSystemStatusMock: vi.fn() }));

vi.mock('../../contexts/useSystemStatus', () => ({
  useSystemStatus: useSystemStatusMock,
}));

import SystemStatus from './SystemStatus';

const readyStatus = {
  overall: {
    status: 'ready',
    title: 'Demo ready',
    message: 'You can submit and review loan applications.',
  },
  checked_at: '2026-09-04T10:20:30Z',
  stale_after_seconds: 90,
  stale: false,
  capabilities: [
    {
      id: 'submit_application',
      label: 'Submit an application',
      status: 'ready',
      message: 'Online form and PDF upload are available.',
      endpoint: 'https://internal.example.test/submit',
    },
    {
      id: 'process_documents',
      label: 'Process documents',
      status: 'ready',
      message: 'Uploaded documents can be extracted and validated.',
    },
    {
      id: 'generate_decision',
      label: 'Generate a loan decision',
      status: 'ready',
      message: 'Agent processing is available. Results may take 2–4 minutes.',
    },
    {
      id: 'view_applications',
      label: 'View applications',
      status: 'ready',
      message: 'Application history and processing details are available.',
    },
    {
      id: 'internal_debug_capability',
      label: 'Internal debug capability',
      status: 'ready',
      message: 'This is not a user capability.',
    },
  ],
  dependencies: [
    {
      id: 'postgresql',
      label: 'PostgreSQL',
      status: 'ready',
      evidence: 'live_check',
      message: 'Application storage is reachable.',
      checked_at: '2026-09-04T10:20:29Z',
      last_success_at: null,
      last_failure_at: null,
      endpoint: 'https://internal.example.test/database',
    },
    {
      id: 'openllmetry',
      label: 'OpenLLMetry',
      status: 'not_configured',
      evidence: 'not_verified',
      message: 'Tracing is not configured.',
      checked_at: null,
      last_success_at: null,
      last_failure_at: null,
    },
  ],
};

const contextValue = (overrides = {}) => ({
  status: readyStatus,
  isLoading: false,
  isRefreshing: false,
  error: '',
  refresh: vi.fn().mockResolvedValue(readyStatus),
  checkedAtLabel: 'Checked just now',
  ...overrides,
});

describe('SystemStatus', () => {
  beforeEach(() => {
    useSystemStatusMock.mockReset();
    useSystemStatusMock.mockReturnValue(contextValue());
  });

  it('shows exactly four user capabilities without exposing raw IDs or URLs', () => {
    render(<SystemStatus />);

    const capabilities = screen.getByRole('list', { name: 'Demo capabilities' });
    expect(within(capabilities).getAllByRole('listitem')).toHaveLength(4);
    expect(within(capabilities).getByText('Submit an application')).toBeVisible();
    expect(within(capabilities).getByText('Process documents')).toBeVisible();
    expect(within(capabilities).getByText('Generate a loan decision')).toBeVisible();
    expect(within(capabilities).getByText('View applications')).toBeVisible();
    expect(screen.queryByText('submit_application')).not.toBeInTheDocument();
    expect(screen.queryByText('Internal debug capability')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('https://internal.example.test');
  });

  it('pairs every capability status word with a visible status icon', () => {
    render(<SystemStatus />);

    const capabilityCards = within(
      screen.getByRole('list', { name: 'Demo capabilities' })
    ).getAllByRole('listitem');

    capabilityCards.forEach((card) => {
      expect(within(card).getByText('Ready')).toBeVisible();
      expect(card.querySelector('svg')).not.toBeNull();
    });
  });

  it('starts technical details collapsed and supports keyboard activation', () => {
    render(<SystemStatus />);

    const toggle = screen.getByRole('button', { name: 'Technical details' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    toggle.focus();
    fireEvent.keyDown(toggle, { key: 'Enter', code: 'Enter' });
    fireEvent.click(toggle, { detail: 0 });

    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('PostgreSQL')).toBeVisible();
  });

  it('preserves capability cards and shows inline progress during refresh', () => {
    useSystemStatusMock.mockReturnValue(contextValue({ isRefreshing: true }));

    render(<SystemStatus />);

    expect(within(screen.getByRole('list', { name: 'Demo capabilities' })).getAllByRole('listitem'))
      .toHaveLength(4);
    expect(screen.getByText('Checking latest status', { selector: 'div' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled();
  });

  it('announces only a completed manual refresh, not the ticking relative label', () => {
    const value = contextValue();
    useSystemStatusMock.mockImplementation(() => value);
    const { rerender } = render(<SystemStatus />);

    expect(screen.getByText('Checked just now')).not.toHaveAttribute('aria-live');
    expect(screen.queryByText(/Demo status refreshed/)).not.toBeInTheDocument();

    value.isRefreshing = true;
    rerender(<SystemStatus />);
    value.isRefreshing = false;
    rerender(<SystemStatus />);

    expect(screen.getByText('Demo status refreshed. Demo ready.')).toHaveAttribute(
      'aria-live',
      'polite'
    );
  });

  it('shows a safe unavailable state with a Retry action', () => {
    const refresh = vi.fn().mockRejectedValue(new Error('provider secret'));
    useSystemStatusMock.mockReturnValue(contextValue({
      status: null,
      error: 'Demo status is currently unavailable.',
      refresh,
      checkedAtLabel: '',
    }));

    render(<SystemStatus />);

    expect(screen.getByRole('heading', { name: 'Status unavailable' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent('provider secret');
  });

  it('makes stale status explicit without turning the relative ticker into a live region', () => {
    useSystemStatusMock.mockReturnValue(contextValue({
      status: { ...readyStatus, stale: true },
      checkedAtLabel: 'Status data is out of date',
    }));

    render(<SystemStatus />);

    expect(screen.getByText('Status data is out of date')).toBeVisible();
    expect(screen.getByText(/Refresh before relying on these results/)).toBeVisible();
    expect(screen.getByText('Status data is out of date')).not.toHaveAttribute('aria-live');
  });

  it('states that OpenLLMetry does not affect demo availability', () => {
    render(<SystemStatus />);
    fireEvent.click(screen.getByRole('button', { name: 'Technical details' }));

    const openLLMetryRow = screen.getByRole('listitem', { name: /OpenLLMetry/ });
    expect(within(openLLMetryRow).getByText('Does not affect demo availability.')).toBeVisible();
    expect(within(openLLMetryRow).getByText('Not configured')).toBeVisible();
    expect(openLLMetryRow.querySelector('svg')).not.toBeNull();
  });
});
