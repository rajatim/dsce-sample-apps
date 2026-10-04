import React, { StrictMode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { authFetchMock, setPanelContentMock } = vi.hoisted(() => ({
  authFetchMock: vi.fn(),
  setPanelContentMock: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  authFetch: authFetchMock,
}));

vi.mock('../CapabilityNotice/CapabilityNotice', () => ({ default: ({ capabilityIds }) => (
  <div data-testid="capability-notice" data-capability-ids={capabilityIds.join(',')} />
)}));

vi.mock('../../contexts/PanelContext', async () => {
  const ReactModule = await import('react');
  return {
    default: ReactModule.createContext({
      setIsPanelOpen: vi.fn(),
      setPanelContent: setPanelContentMock,
    }),
  };
});

vi.mock('react-markdown', () => ({
  default: ({ children }) => <div>{children}</div>,
}));

import MyApplications from './MyApplications';
import i18n from '../../i18n/config';

const application = (status, overrides = {}) => ({
  app_id_str: `app-${status}`,
  applicant_name: 'Tom Miller',
  loan_type: 'Home Renovation',
  amount: 50000,
  status,
  validation_comments: '',
  submitted_date: '2026-09-01',
  created_at: '2026-09-01T07:49:42Z',
  ...overrides,
});

const apiResponse = (data) => ({
  ok: true,
  json: async () => ({items: data, total: data.length, page: 1, page_size: 50,
    total_pages: 1, has_active_applications: data.some(r => ['processing', 'retrying', 'pending'].includes(r.status.toLowerCase()))}),
});

const flushRequests = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('MyApplications live statuses', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    await i18n.changeLanguage('en-US');
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
  });

  it('requests only view applications and places the notice after heading before loading', () => {
    render(<MyApplications />);
    const heading = screen.getByRole('heading', { name: 'My Applications' });
    const notice = screen.getByTestId('capability-notice');
    expect(notice).toHaveAttribute('data-capability-ids', 'view_applications');
    expect(heading.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(notice.compareDocumentPosition(screen.getByText('Loading applications...')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('refreshes active applications and stops after they reach a final status', async () => {
    authFetchMock
      .mockResolvedValueOnce(apiResponse([application('Processing')]))
      .mockResolvedValueOnce(apiResponse([application('Rejected')]));

    render(<MyApplications />);
    await flushRequests();
    expect(authFetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(authFetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Rejected')).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(authFetchMock).toHaveBeenCalledTimes(2);
  });

  it('displays distinct stored timestamps including seconds for the same date', async () => {
    authFetchMock.mockResolvedValue(apiResponse([
      application('Passed', {app_id_str: 'first', created_at: '2026-10-02T07:49:42Z'}),
      application('Passed', {app_id_str: 'second', created_at: '2026-10-02T07:51:38Z'}),
    ]));
    render(<MyApplications />);
    await flushRequests();
    for (const value of ['2026-10-02T07:49:42Z', '2026-10-02T07:51:38Z']) {
      const expected = new Intl.DateTimeFormat('en-US', {dateStyle: 'medium', timeStyle: 'medium'}).format(new Date(value));
      expect(screen.getByText(expected)).toBeVisible();
    }
  });

  it('does not poll applications that are already complete', async () => {
    authFetchMock.mockResolvedValue(apiResponse([application('Passed')]));

    render(<MyApplications />);
    await flushRequests();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(authFetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not start another poll while the previous request is unresolved', async () => {
    let resolvePoll;
    authFetchMock
      .mockResolvedValueOnce(apiResponse([application('Processing')]))
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolvePoll = resolve;
      }));

    render(<MyApplications />);
    await flushRequests();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(authFetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(authFetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolvePoll(apiResponse([application('Rejected')]));
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it('deduplicates the initial request when React StrictMode reruns effects', async () => {
    let resolveInitial;
    authFetchMock.mockImplementation(() => new Promise((resolve) => {
      resolveInitial = resolve;
    }));

    render(<StrictMode><MyApplications /></StrictMode>);
    await flushRequests();

    expect(authFetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveInitial(apiResponse([application('Passed')]));
      await Promise.resolve();
    });
  });

  it('uses meaningful colors and keeps full validation details out of the table', async () => {
    authFetchMock.mockResolvedValue(
      apiResponse([
        application('Processing'),
        application('Retrying'),
        application('Passed'),
        application('Rejected'),
        application('Processing Failed', {
          validation_comments: 'A very long validation explanation that belongs in the side panel.',
        }),
      ])
    );

    render(<MyApplications />);
    await flushRequests();

    expect(screen.getByText('Processing').closest('.cds--tag')).toHaveClass('cds--tag--blue');
    expect(screen.getByText('Retrying').closest('.cds--tag')).toHaveClass('cds--tag--purple');
    expect(screen.getByText('Passed').closest('.cds--tag')).toHaveClass('cds--tag--green');
    expect(screen.getByText('Rejected').closest('.cds--tag')).toHaveClass('cds--tag--red');
    expect(screen.getByText('Processing Failed').closest('.cds--tag')).toHaveClass('cds--tag--red');
    expect(screen.getByRole('columnheader', { name: /Details/ })).toBeVisible();
    expect(screen.getAllByText('View processing details')).toHaveLength(5);
    expect(
      screen.queryByText('A very long validation explanation that belongs in the side panel.')
    ).not.toBeInTheDocument();
  });

  it('localizes known presentation without mutating API data or unknown statuses', async () => {
    await i18n.changeLanguage('zh-TW');
    const source = [
      application('Passed'),
      application('Manual review required', { app_id_str: 'app-manual' }),
    ];
    const before = structuredClone(source);
    authFetchMock.mockResolvedValue(apiResponse(source));

    render(<MyApplications />);
    await flushRequests();

    expect(screen.getByRole('heading', { name: '我的申請' })).toBeVisible();
    expect(screen.getByRole('columnheader', { name: /申請編號/ })).toBeVisible();
    expect(screen.getByText('已通過')).toBeVisible();
    expect(screen.getByRole('combobox', {name: '頁碼'})).toBeInTheDocument();
    expect(screen.getByText('Manual review required')).toBeVisible();
    expect(screen.getAllByText('查看處理詳細資料')).toHaveLength(2);
    expect(source).toEqual(before);
  });
});


describe('server table navigation', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    await i18n.changeLanguage('en-US');
  });
  const pageResponse = (page, active = false, id = `page-${page}`) => ({
    ok: true, json: async () => ({items: [application('Passed', {app_id_str: id})],
      total: 121, page, page_size: 50, total_pages: 3, has_active_applications: active}),
  });
  it('sends page and all seven sorting choices to the API without sorting locally', async () => {
    authFetchMock.mockImplementation(async url => pageResponse(Number(new URL(url, 'http://local').searchParams.get('page'))));
    render(<MyApplications />);
    await flushRequests();
    expect(authFetchMock.mock.calls[0][0]).toContain('sort_by=created_at&sort_direction=desc');
    fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
    await flushRequests();
    expect(authFetchMock.mock.lastCall[0]).toContain('page=2&');
    for (const [label, field] of [['Amount','amount'], ['Application ID','app_id_str'],
      ['Applicant Name','applicant_name'], ['Loan Type','loan_type'], ['Status','status'],
      ['Details','validation_comments'], ['Submitted Time','created_at']]) {
      for (const direction of ['asc', 'desc']) {
        fireEvent.click(screen.getByRole('button', {name: new RegExp(label)}));
        await flushRequests();
        expect(authFetchMock.mock.lastCall[0]).toContain(`page=1&page_size=50&sort_by=${field}&sort_direction=${direction}`);
      }
    }
  });
  it('polls activity on another page and preserves the selected page', async () => {
    authFetchMock.mockImplementation(async url => pageResponse(Number(new URL(url, 'http://local').searchParams.get('page')), true));
    render(<MyApplications />);
    await flushRequests();
    fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
    await flushRequests();
    await act(async () => {await vi.advanceTimersByTimeAsync(5000);});
    expect(authFetchMock).toHaveBeenCalledTimes(3);
    expect(authFetchMock.mock.lastCall[0]).toContain('page=2&');
  });
  it('ignores an old page response after a new sort', async () => {
    let resolveOld;
    authFetchMock.mockResolvedValueOnce(pageResponse(1))
      .mockImplementationOnce(() => new Promise(resolve => {resolveOld = resolve;}))
      .mockResolvedValueOnce(pageResponse(1, false, 'latest-sort'));
    render(<MyApplications />);
    await flushRequests();
    fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
    await flushRequests();
    fireEvent.click(screen.getByRole('button', {name: /Amount/}));
    await flushRequests();
    await act(async () => {resolveOld(pageResponse(2, false, 'obsolete-page'));});
    expect(screen.getByText('latest-sort')).toBeVisible();
    expect(screen.queryByText('obsolete-page')).not.toBeInTheDocument();
  });
  it('refreshes the current page after a detail change, even during an older poll', async () => {
    let resolvePoll;
    authFetchMock.mockResolvedValueOnce(pageResponse(1, true))
      .mockResolvedValueOnce(pageResponse(2, true))
      .mockImplementationOnce(() => new Promise(resolve => {resolvePoll = resolve;}))
      .mockResolvedValueOnce(pageResponse(2, false, 'after-retry'));
    render(<MyApplications />);
    await flushRequests();
    fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
    await flushRequests();
    fireEvent.click(screen.getByText('page-2'));
    const panel = setPanelContentMock.mock.lastCall[0];
    await act(async () => {await vi.advanceTimersByTimeAsync(5000);});
    let refresh;
    act(() => {refresh = panel.props.onApplicationChange(application('Retrying'));});
    await act(async () => {resolvePoll(pageResponse(2, true)); await refresh;});
    expect(authFetchMock).toHaveBeenCalledTimes(4);
    expect(authFetchMock.mock.lastCall[0]).toContain('page=2&');
    expect(screen.getByText('after-retry')).toBeVisible();
  });

  it('shows pending navigation while retaining the resolved page range', async () => {
    let resolvePage;
    authFetchMock.mockResolvedValueOnce(pageResponse(1))
      .mockImplementationOnce(() => new Promise(resolve => {resolvePage = resolve;}));
    render(<MyApplications />);
    await flushRequests();
    fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
    await flushRequests();
    expect(screen.getByText('Updating applications...')).toBeVisible();
    expect(screen.getByText('1–50 of 121 items')).toBeVisible();
    expect(screen.queryByText('51–100 of 121 items')).not.toBeInTheDocument();
    await act(async () => {resolvePage(pageResponse(2));});
    expect(screen.getByText('51–100 of 121 items')).toBeVisible();
    expect(screen.queryByText('Updating applications...')).not.toBeInTheDocument();
  });
  it('invalidates all pre-update requests when revisiting a pending query', async () => {
    let resolveOldPage2, resolveOldSort;
    authFetchMock.mockResolvedValueOnce(pageResponse(1))
      .mockImplementationOnce(() => new Promise(resolve => {resolveOldPage2 = resolve;}))
      .mockImplementationOnce(() => new Promise(resolve => {resolveOldSort = resolve;}))
      .mockResolvedValue(pageResponse(1, false, 'fresh-after-update'));
    render(<MyApplications />);
    await flushRequests();
    fireEvent.click(screen.getByText('page-1'));
    const panel = setPanelContentMock.mock.lastCall[0];
    fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
    await flushRequests();
    fireEvent.change(screen.getByRole('combobox', {name: 'Page number'}), {target: {value: '1'}});
    await flushRequests();
    act(() => {panel.props.onApplicationChange(application('Retrying'));});
    await flushRequests();
    fireEvent.change(screen.getByRole('combobox', {name: 'Page number'}), {target: {value: '2'}});
    await flushRequests();
    await act(async () => {resolveOldSort(pageResponse(1, false, 'old-sort'));});
    await flushRequests();
    await act(async () => {resolveOldPage2(pageResponse(2, false, 'old-page'));});
    expect(screen.getByText('fresh-after-update')).toBeVisible();
    expect(screen.queryByText('old-sort')).not.toBeInTheDocument();
    expect(screen.queryByText('old-page')).not.toBeInTheDocument();
  });

});
