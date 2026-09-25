import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import readyContract from '../../../../contracts/system-status-ready.json';

const { useSystemStatusMock } = vi.hoisted(() => ({ useSystemStatusMock: vi.fn() }));

vi.mock('../../contexts/useSystemStatus', () => ({
  useSystemStatus: useSystemStatusMock,
}));

import SystemStatus from './SystemStatus';
import i18n from '../../i18n/config';

const readyStatus = {
  ...readyContract,
  capabilities: [
    ...readyContract.capabilities.map((capability) => (
      capability.id === 'submit_application'
        ? { ...capability, endpoint: 'https://internal.example.test/submit' }
        : capability
    )),
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
  isStale: false,
  ...overrides,
});

describe('SystemStatus', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
    useSystemStatusMock.mockReset();
    useSystemStatusMock.mockReturnValue(contextValue());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('refreshes lightweight status after five minutes while visible and online', async () => {
    vi.useFakeTimers();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({ refresh }));

    render(<SystemStatus />);
    await act(async () => {
      vi.advanceTimersByTime(300_000);
      await Promise.resolve();
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('does not auto-refresh while the status page is hidden', async () => {
    vi.useFakeTimers();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({ refresh }));

    render(<SystemStatus />);
    await act(async () => {
      vi.advanceTimersByTime(300_000);
      await Promise.resolve();
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it('does not auto-refresh while the browser is offline', async () => {
    vi.useFakeTimers();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({ refresh }));

    render(<SystemStatus />);
    await act(async () => {
      vi.advanceTimersByTime(300_000);
      await Promise.resolve();
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it('refreshes an overdue check when the page becomes visible again', async () => {
    vi.useFakeTimers();
    let visibilityState = 'hidden';
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibilityState);
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({ refresh }));

    render(<SystemStatus />);
    act(() => vi.advanceTimersByTime(300_000));
    expect(refresh).not.toHaveBeenCalled();

    visibilityState = 'visible';
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('refreshes an overdue check when the browser comes online again', async () => {
    vi.useFakeTimers();
    let online = false;
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.spyOn(navigator, 'onLine', 'get').mockImplementation(() => online);
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({ refresh }));

    render(<SystemStatus />);
    act(() => vi.advanceTimersByTime(300_000));
    expect(refresh).not.toHaveBeenCalled();

    online = true;
    await act(async () => {
      window.dispatchEvent(new Event('online'));
      await Promise.resolve();
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('does not refresh early on visibility or online events and cleans up on unmount', () => {
    vi.useFakeTimers();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({ refresh }));

    const { unmount } = render(<SystemStatus />);
    act(() => {
      vi.advanceTimersByTime(299_999);
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('online'));
    });
    expect(refresh).not.toHaveBeenCalled();

    unmount();
    act(() => {
      vi.advanceTimersByTime(300_000);
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('online'));
    });
    expect(refresh).not.toHaveBeenCalled();
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

  it('renders the approved aggregator copy without substituting generic system copy', () => {
    render(<SystemStatus />);

    expect(screen.getByRole('heading', { name: 'Demo ready' })).toBeVisible();
    expect(screen.getByText('You can submit and review loan applications.')).toBeVisible();
    expect(screen.getByText('Online form and PDF upload are available.')).toBeVisible();
    expect(screen.getByText('Uploaded documents can be extracted and validated.')).toBeVisible();
    expect(screen.getByText('Agent processing is available. Results may take 2–4 minutes.')).toBeVisible();
    expect(screen.getByText('Application history and processing details are available.')).toBeVisible();
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

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    value.isRefreshing = true;
    rerender(<SystemStatus />);
    value.isRefreshing = false;
    rerender(<SystemStatus />);

    const liveRegion = screen
      .getByText('Demo status refreshed. Demo ready.')
      .closest('[aria-live="polite"]');
    expect(liveRegion).toHaveAttribute(
      'aria-live',
      'polite'
    );

    const firstAnnouncementNode = liveRegion.firstChild;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    value.isRefreshing = true;
    rerender(<SystemStatus />);
    value.isRefreshing = false;
    rerender(<SystemStatus />);

    expect(liveRegion.firstChild).not.toBe(firstAnnouncementNode);
  });

  it('does not announce a completed automatic refresh', async () => {
    vi.useFakeTimers();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    const value = contextValue();
    useSystemStatusMock.mockImplementation(() => value);
    const { rerender } = render(<SystemStatus />);

    await act(async () => {
      vi.advanceTimersByTime(300_000);
      await Promise.resolve();
    });
    expect(value.refresh).toHaveBeenCalledTimes(1);

    value.isRefreshing = true;
    rerender(<SystemStatus />);
    value.isRefreshing = false;
    rerender(<SystemStatus />);

    expect(screen.queryByText(/Demo status refreshed/)).not.toBeInTheDocument();
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
      isStale: true,
    }));

    render(<SystemStatus />);

    expect(screen.getByText('Status data is out of date')).toBeVisible();
    expect(screen.getByText(/Refresh before relying on these results/)).toBeVisible();
    expect(screen.getByText('Status data is out of date')).not.toHaveAttribute('aria-live');

    expect(screen.getByRole('heading', { name: 'Status unavailable' })).toBeVisible();
    const capabilities = screen.getByRole('list', { name: 'Demo capabilities' });
    expect(within(capabilities).queryByText('Ready')).not.toBeInTheDocument();
    expect(within(capabilities).getAllByText('Status unavailable')).toHaveLength(4);
  });

  it('shows no Ready dependency presentation when stale technical details are expanded', () => {
    useSystemStatusMock.mockReturnValue(contextValue({
      status: { ...readyStatus, stale: false },
      checkedAtLabel: 'Status data is out of date',
      isStale: true,
    }));

    render(<SystemStatus />);
    fireEvent.click(screen.getByRole('button', { name: 'Technical details' }));

    const dependencies = screen.getByRole('list', { name: 'Technical dependencies' });
    expect(within(dependencies).queryByText('Ready')).not.toBeInTheDocument();
    expect(within(dependencies).getAllByText('Status unavailable')).toHaveLength(2);
  });

  it('announces the effective unavailable status after a stale refresh completes', () => {
    const value = contextValue({
      status: { ...readyStatus, stale: false },
      checkedAtLabel: 'Status data is out of date',
      isStale: true,
    });
    useSystemStatusMock.mockImplementation(() => value);
    const { rerender } = render(<SystemStatus />);

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    value.isRefreshing = true;
    rerender(<SystemStatus />);
    value.isRefreshing = false;
    rerender(<SystemStatus />);

    expect(screen.getByText('Demo status refreshed. Status unavailable.')).toBeVisible();
    expect(screen.queryByText('Demo status refreshed. Demo ready.')).not.toBeInTheDocument();
  });

  it('shows latest fixed-agent success or failure and no recent run ahead of checked_at', () => {
    useSystemStatusMock.mockReturnValue(contextValue({
      status: {
        ...readyStatus,
        dependencies: [
          {
            id: 'document_processing_agent',
            status: 'ready',
            evidence: 'live_check',
            message: 'Agent is registered.',
            checked_at: '2026-09-05T10:00:00Z',
            last_success_at: '2026-09-05T08:00:00Z',
            last_failure_at: '2026-09-05T09:00:00Z',
          },
          {
            id: 'document_validation_agent',
            status: 'ready',
            evidence: 'live_check',
            message: 'Agent is registered.',
            checked_at: '2026-09-05T10:00:00Z',
            last_success_at: null,
            last_failure_at: null,
          },
          {
            id: 'final_decision_agent',
            status: 'ready',
            evidence: 'live_check',
            message: 'Agent is registered.',
            checked_at: '2026-09-05T10:00:00Z',
            last_success_at: '2026-09-05T09:30:00Z',
            last_failure_at: '2026-09-05T09:00:00Z',
          },
        ],
      },
    }));
    render(<SystemStatus />);
    fireEvent.click(screen.getByRole('button', { name: 'Technical details' }));

    const processor = screen.getByRole('listitem', { name: /Document Processing Agent/ });
    const validator = screen.getByRole('listitem', { name: /Document Validation Agent/ });
    const decision = screen.getByRole('listitem', { name: /Final Decision Agent/ });
    expect(within(processor).getByText(/^Last failed run /)).toBeVisible();
    expect(within(validator).getByText('No recent run')).toBeVisible();
    expect(within(decision).getByText(/^Last successful run /)).toBeVisible();
    expect(within(validator).queryByText(/^Checked at /)).not.toBeInTheDocument();
  });

  it('shows a recent watsonx quota problem as blocked work with support identifiers', async () => {
    await i18n.changeLanguage('zh-TW');
    const problem = {
      category: 'provider_quota',
      service: 'watsonx_ai',
      stage: 'document_processing_agent',
      provider_code: 'token_quota_reached',
      http_status: 403,
      trace_id: 'trace-status-456',
      documentation_url: 'https://cloud.ibm.com/apidocs/watsonx-ai#text-chat',
      retryable_now: false,
      action: 'check_service_configuration',
    };
    useSystemStatusMock.mockReturnValue(contextValue({
      status: {
        ...readyStatus,
        overall: { status: 'limited', title: 'ignored', message: 'ignored' },
        capabilities: readyStatus.capabilities.map((capability) => (
          ['process_documents', 'generate_decision'].includes(capability.id)
            ? { ...capability, status: 'limited', problem }
            : capability
        )),
        dependencies: [
          {
            id: 'watsonx_ai',
            status: 'limited',
            evidence: 'recent_execution',
            message: 'watsonx.ai is reachable, but the latest model request failed.',
            checked_at: '2026-09-06T03:54:39Z',
            last_success_at: null,
            last_failure_at: '2026-09-06T03:52:12Z',
            problem,
          },
          {
            id: 'document_processing_agent',
            status: 'limited',
            evidence: 'recent_execution',
            message: 'Agent is reachable, but its most recent run failed.',
            checked_at: '2026-09-06T03:54:39Z',
            last_success_at: null,
            last_failure_at: '2026-09-06T03:52:12Z',
            problem,
          },
        ],
      },
      checkedAtLabel: '剛剛檢查',
    }));

    render(<SystemStatus />);

    const capabilities = screen.getByRole('list', { name: 'Demo 功能' });
    const processDocuments = within(capabilities)
      .getByRole('heading', { name: '處理文件' })
      .closest('li');
    expect(within(processDocuments).getByText(/目前無法完成文件處理/)).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '技術詳細資料' }));
    const watsonx = screen.getByRole('listitem', { name: /watsonx.ai/ });
    expect(within(watsonx).getByText('token_quota_reached')).toBeVisible();
    expect(within(watsonx).getByText('403 Forbidden')).toBeVisible();
    expect(within(watsonx).getByText('trace-status-456')).toBeVisible();
    expect(within(watsonx).getByText(/最近一次模型請求因額度或服務關聯問題失敗/)).toBeVisible();
  });

  it('states that OpenLLMetry does not affect demo availability', () => {
    render(<SystemStatus />);
    fireEvent.click(screen.getByRole('button', { name: 'Technical details' }));

    const openLLMetryRow = screen.getByRole('listitem', { name: /OpenLLMetry/ });
    expect(within(openLLMetryRow).getByText('Does not affect demo availability.')).toBeVisible();
    expect(within(openLLMetryRow).getByText('Not configured')).toBeVisible();
    expect(openLLMetryRow.querySelector('svg')).not.toBeNull();
  });

  it('localizes known status presentation without refreshing or exposing internal data', async () => {
    await i18n.changeLanguage('zh-TW');
    const refresh = vi.fn().mockResolvedValue(readyStatus);
    useSystemStatusMock.mockReturnValue(contextValue({
      refresh,
      checkedAtLabel: '剛剛檢查',
    }));

    render(<SystemStatus />);
    expect(screen.getByRole('heading', { name: 'Demo 已就緒' })).toBeVisible();
    expect(screen.getByText('您可以送出及查看貸款申請。')).toBeVisible();
    expect(screen.getByText('線上表單與 PDF 上傳皆可使用。')).toBeVisible();
    expect(screen.getByRole('list', { name: 'Demo 功能' })).toBeVisible();
    expect(screen.getByText('剛剛檢查')).toBeVisible();
    expect(refresh).not.toHaveBeenCalled();

    await i18n.changeLanguage('zh-CN');
    expect(screen.getByRole('heading', { name: 'Demo 已就绪' })).toBeVisible();
    expect(refresh).not.toHaveBeenCalled();
  });
});
