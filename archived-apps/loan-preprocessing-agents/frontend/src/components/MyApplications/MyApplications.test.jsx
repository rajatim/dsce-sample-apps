import React, { StrictMode } from 'react';
import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { authFetchMock } = vi.hoisted(() => ({
  authFetchMock: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  authFetch: authFetchMock,
}));

vi.mock('../../contexts/useSystemStatus', () => ({
  useSystemStatus: () => ({
    status: { capabilities: [] },
    isLoading: false,
  }),
}));

vi.mock('../../contexts/PanelContext', async () => {
  const ReactModule = await import('react');
  return {
    default: ReactModule.createContext({
      setIsPanelOpen: vi.fn(),
      setPanelContent: vi.fn(),
    }),
  };
});

vi.mock('react-markdown', () => ({
  default: ({ children }) => <div>{children}</div>,
}));

vi.mock('@carbon/react', () => ({
  DataTable: ({ rows, headers, children }) =>
    children({
      rows: rows.map((row) => ({
        id: row.id,
        cells: headers.map((header) => ({
          id: `${row.id}-${header.key}`,
          info: { header: header.key },
          value: row[header.key],
        })),
      })),
      headers,
      getTableProps: () => ({}),
      getHeaderProps: ({ header }) => ({ key: header.key }),
      getRowProps: ({ row }) => ({ key: row.id }),
    }),
  Table: (props) => <table {...props} />,
  TableHead: (props) => <thead {...props} />,
  TableRow: (props) => <tr {...props} />,
  TableHeader: (props) => <th {...props} />,
  TableBody: (props) => <tbody {...props} />,
  TableCell: (props) => <td {...props} />,
  TableContainer: (props) => <div {...props} />,
  Loading: ({ description }) => <div role="status">{description}</div>,
  InlineNotification: ({ title, subtitle }) => (
    <div role="alert">{title}: {subtitle}</div>
  ),
  Tag: ({ type, children }) => <span data-tag-type={type}>{children}</span>,
}));

import MyApplications from './MyApplications';

const application = (status, overrides = {}) => ({
  app_id_str: `app-${status}`,
  applicant_name: 'Tom Miller',
  loan_type: 'Home Renovation',
  amount: 50000,
  status,
  validation_comments: '',
  submitted_date: '2026-09-01',
  ...overrides,
});

const apiResponse = (data) => ({
  ok: true,
  json: async () => data,
});

const flushRequests = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('MyApplications live statuses', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
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

    expect(screen.getByText('Processing')).toHaveAttribute('data-tag-type', 'blue');
    expect(screen.getByText('Retrying')).toHaveAttribute('data-tag-type', 'purple');
    expect(screen.getByText('Passed')).toHaveAttribute('data-tag-type', 'green');
    expect(screen.getByText('Rejected')).toHaveAttribute('data-tag-type', 'red');
    expect(screen.getByText('Processing Failed')).toHaveAttribute('data-tag-type', 'red');
    expect(screen.getByRole('columnheader', { name: 'Details' })).toBeVisible();
    expect(screen.getAllByText('View processing details')).toHaveLength(5);
    expect(
      screen.queryByText('A very long validation explanation that belongs in the side panel.')
    ).not.toBeInTheDocument();
  });
});
