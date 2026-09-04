import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const { fetchSystemStatusMock } = vi.hoisted(() => ({ fetchSystemStatusMock: vi.fn() }));
vi.mock('../services/systemStatus', () => ({ fetchSystemStatus: fetchSystemStatusMock }));

import { SystemStatusProvider } from './SystemStatusContext';
import { useSystemStatus } from './useSystemStatus';

const payload = {
  overall: { status: 'ready', title: 'Ready', message: 'All systems are ready.' },
  checked_at: new Date().toISOString(), stale_after_seconds: 300, stale: false,
  capabilities: [], dependencies: [],
};

const Probe = () => {
  const { status, isLoading, isRefreshing, error, refresh, checkedAtLabel } = useSystemStatus();
  return <div>
    <span data-testid="loading">{String(isLoading)}</span>
    <span data-testid="refreshing">{String(isRefreshing)}</span>
    <span data-testid="status">{status?.overall.status || 'none'}</span>
    <span data-testid="error">{error || ''}</span>
    <span aria-live="polite" data-testid="label">{checkedAtLabel}</span>
    <button type="button" onClick={refresh}>Refresh</button>
  </div>;
};

describe('SystemStatusProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchSystemStatusMock.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it('loads once when mounted and exposes the successful payload', async () => {
    fetchSystemStatusMock.mockResolvedValue(payload);
    render(<SystemStatusProvider><Probe /></SystemStatusProvider>);
    expect(screen.getByTestId('loading')).toHaveTextContent('true');
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId('status')).toHaveTextContent('ready');
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(1);
  });

  it('aborts the initial request when unmounted', () => {
    fetchSystemStatusMock.mockReturnValue(new Promise(() => {}));
    const { unmount } = render(<SystemStatusProvider><Probe /></SystemStatusProvider>);
    const { signal } = fetchSystemStatusMock.mock.calls[0][0];
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('preserves the last success and suppresses duplicate manual refreshes', async () => {
    fetchSystemStatusMock.mockResolvedValueOnce(payload).mockReturnValue(new Promise(() => {}));
    render(<SystemStatusProvider><Probe /></SystemStatusProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId('status')).toHaveTextContent('ready');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(screen.getByTestId('status')).toHaveTextContent('ready');
    expect(screen.getByTestId('refreshing')).toHaveTextContent('true');
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(2);
  });

  it('updates the relative label every 30 seconds without fetching again', async () => {
    fetchSystemStatusMock.mockResolvedValue(payload);
    render(<SystemStatusProvider><Probe /></SystemStatusProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId('status')).toHaveTextContent('ready');
    const initialLabel = screen.getByTestId('label').textContent;
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByTestId('label').textContent).not.toBe(initialLabel);
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(1);
  });
});
