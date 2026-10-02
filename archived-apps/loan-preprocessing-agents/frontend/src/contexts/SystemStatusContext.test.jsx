import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const { fetchSystemStatusMock } = vi.hoisted(() => ({ fetchSystemStatusMock: vi.fn() }));
vi.mock('../services/systemStatus', () => ({ fetchSystemStatus: fetchSystemStatusMock }));

import { SystemStatusProvider } from './SystemStatusContext';
import { useSystemStatus } from './useSystemStatus';
import i18n from '../i18n/config';

const payload = {
  overall: { status: 'ready', title: 'Ready', message: 'All systems are ready.' },
  checked_at: new Date().toISOString(), stale_after_seconds: 300, stale: false,
  capabilities: [], dependencies: [],
};

const Probe = ({ onRender }) => {
  onRender?.();
  const {
    status,
    isLoading,
    isRefreshing,
    error,
    refresh,
    checkedAtLabel,
    isStale,
  } = useSystemStatus();
  return <div>
    <span data-testid="loading">{String(isLoading)}</span>
    <span data-testid="refreshing">{String(isRefreshing)}</span>
    <span data-testid="status">{status?.overall.status || 'none'}</span>
    <span data-testid="error">{error || ''}</span>
    <span data-testid="label">{checkedAtLabel}</span>
    <span data-testid="stale">{String(isStale)}</span>
    <button type="button" onClick={refresh}>Refresh</button>
  </div>;
};

describe('SystemStatusProvider', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
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

  it('does not let an aborted StrictMode request settle the restarted request', async () => {
    let rejectFirst;
    const first = new Promise((_resolve, reject) => { rejectFirst = reject; });
    const second = new Promise(() => {});
    fetchSystemStatusMock.mockReturnValueOnce(first).mockReturnValueOnce(second);
    render(<React.StrictMode><SystemStatusProvider><Probe /></SystemStatusProvider></React.StrictMode>);
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(2);
    await act(async () => { rejectFirst(new DOMException('aborted', 'AbortError')); await Promise.resolve(); });
    expect(screen.getByTestId('loading')).toHaveTextContent('true');
    expect(screen.getByTestId('error')).toHaveTextContent('');
  });

  it('requires the provider when using the hook outside it', () => {
    const Outside = () => {
      useSystemStatus();
      return <span>outside</span>;
    };
    expect(() => render(<Outside />)).toThrow('useSystemStatus must be used within SystemStatusProvider');
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
    expect(fetchSystemStatusMock.mock.calls[1][0]).toEqual(expect.objectContaining({ refresh: true }));
  });

  it('updates the relative label every 30 seconds without fetching again', async () => {
    fetchSystemStatusMock.mockResolvedValue({ ...payload, checked_at: new Date(Date.now() - 59_000).toISOString() });
    render(<SystemStatusProvider><Probe /></SystemStatusProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId('status')).toHaveTextContent('ready');
    const initialLabel = screen.getByTestId('label').textContent;
    act(() => vi.advanceTimersByTime(29_000));
    expect(screen.getByTestId('label').textContent).toBe(initialLabel);
    act(() => vi.advanceTimersByTime(1_000));
    expect(screen.getByTestId('label').textContent).not.toBe(initialLabel);
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('label')).not.toHaveAttribute('aria-live');
  });

  it('treats a future server timestamp as stale at receipt', async () => {
    let wallNow = Date.parse('2026-09-05T10:00:00Z');
    let monotonicNow = 5000;
    fetchSystemStatusMock.mockResolvedValue({
      ...payload,
      checked_at: '2026-09-05T10:00:01Z',
      stale_after_seconds: 90,
    });

    render(
      <SystemStatusProvider
        wallClock={() => wallNow}
        monotonicClock={() => monotonicNow}
      >
        <Probe />
      </SystemStatusProvider>,
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(screen.getByTestId('stale')).toHaveTextContent('true');
    expect(screen.getByTestId('label')).toHaveTextContent('Status data is out of date');
    wallNow += 1000;
    monotonicNow += 1000;
  });

  it('uses receipt monotonic elapsed time when the wall clock rolls backward', async () => {
    let wallNow = Date.parse('2026-09-05T10:00:30Z');
    let monotonicNow = 10_000;
    fetchSystemStatusMock.mockResolvedValue({
      ...payload,
      checked_at: '2026-09-05T10:00:00Z',
      stale_after_seconds: 90,
    });

    render(
      <SystemStatusProvider
        wallClock={() => wallNow}
        monotonicClock={() => monotonicNow}
      >
        <Probe />
      </SystemStatusProvider>,
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId('stale')).toHaveTextContent('false');

    wallNow -= 86_400_000;
    monotonicNow += 61_000;
    act(() => vi.advanceTimersByTime(30_000));

    expect(screen.getByTestId('stale')).toHaveTextContent('true');
    expect(screen.getByTestId('label')).toHaveTextContent('Status data is out of date');
  });

  it('updates relative timing language without fetching status again', async () => {
    fetchSystemStatusMock.mockResolvedValue(payload);
    render(<SystemStatusProvider><Probe /></SystemStatusProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId('label')).toHaveTextContent('Checked just now');
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(1);

    await act(async () => { await i18n.changeLanguage('zh-TW'); });
    expect(screen.getByTestId('label')).toHaveTextContent('剛剛檢查');
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(1);
  });
});

const TargetProbe = () => {
  const c = useSystemStatus();
  return <>
    <span data-testid="revision">{c.status?.revision}</span>
    <span data-testid="cos-pending">{String(c.isChecking('cos'))}</span>
    <span data-testid="wxo-pending">{String(c.isChecking('wxo'))}</span>
    <span data-testid="cos-error">{c.checkError('cos')}</span>
    <span data-testid="cos-stale">{String(c.status?.dependencies[0] && c.isDependencyStale(c.status.dependencies[0]))}</span>
    <button onClick={() => c.checkDependency('cos').catch(() => {})}>COS</button>
    <button onClick={() => c.checkDependency('wxo').catch(() => {})}>WXO</button>
    <button onClick={() => c.checkDependency('final_decision_agent').catch(() => {})}>Decision</button>
  </>;
};

describe('targeted status state', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
    fetchSystemStatusMock.mockReset();
  });
  const version = (revision) => ({ ...payload, instance_id: 'process-a', revision });
  it('shares WXO button work and ignores an older response from another group', async () => {
    let resolveCos, resolveWxo;
    fetchSystemStatusMock.mockResolvedValueOnce(version(1))
      .mockReturnValueOnce(new Promise((resolve) => { resolveCos = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveWxo = resolve; }));
    render(<SystemStatusProvider><TargetProbe /></SystemStatusProvider>);
    await act(async () => {});
    fireEvent.click(screen.getByText('COS'));
    fireEvent.click(screen.getByText('WXO'));
    fireEvent.click(screen.getByText('Decision'));
    expect(fetchSystemStatusMock).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId('wxo-pending')).toHaveTextContent('true');
    await act(async () => resolveWxo(version(3)));
    await act(async () => resolveCos(version(2)));
    expect(screen.getByTestId('revision')).toHaveTextContent('3');
    expect(screen.getByTestId('cos-pending')).toHaveTextContent('false');
  });
  it('does not reset freshness when an equal-revision cooldown response arrives late', async () => {
    let resolveCos, resolveWxo;
    let now = 0;
    const clock = () => now;
    const aged = (age) => ({ ...version(1), stale_after_seconds: 90,
      dependencies: [{ id: 'cos', checked_at: payload.checked_at, age_seconds: age, stale: false }] });
    fetchSystemStatusMock.mockResolvedValueOnce(aged(1))
      .mockReturnValueOnce(new Promise((resolve) => { resolveCos = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveWxo = resolve; }));
    render(<SystemStatusProvider monotonicClock={clock}><TargetProbe /></SystemStatusProvider>);
    await act(async () => {});
    fireEvent.click(screen.getByText('COS'));
    fireEvent.click(screen.getByText('WXO'));
    now = 91_000;
    await act(async () => resolveWxo(aged(92)));
    expect(screen.getByTestId('cos-stale')).toHaveTextContent('true');
    await act(async () => resolveCos(aged(1)));
    expect(screen.getByTestId('cos-stale')).toHaveTextContent('true');
  });
  it('retains results and shows a row error when the targeted request fails', async () => {
    fetchSystemStatusMock.mockResolvedValueOnce(version(1)).mockRejectedValueOnce(new Error('private failure'));
    render(<SystemStatusProvider><TargetProbe /></SystemStatusProvider>);
    await act(async () => {});
    await act(async () => fireEvent.click(screen.getByText('COS')));
    expect(screen.getByTestId('revision')).toHaveTextContent('1');
    expect(screen.getByTestId('cos-error')).toHaveTextContent('Demo status is currently unavailable.');
    expect(document.body).not.toHaveTextContent('private failure');
  });
  it('uses the row age even when a different group assembled a fresh snapshot', async () => {
    fetchSystemStatusMock.mockResolvedValue({ ...version(1), checked_at: new Date().toISOString(), stale_after_seconds: 90,
      dependencies: [{ id: 'cos', checked_at: new Date().toISOString(), stale: false, age_seconds: 95 }] });
    render(<SystemStatusProvider><TargetProbe /></SystemStatusProvider>);
    await act(async () => {});
    expect(screen.getByTestId('cos-stale')).toHaveTextContent('true');
  });
});
