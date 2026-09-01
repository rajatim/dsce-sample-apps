import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { authFetchMock } = vi.hoisted(() => ({
  authFetchMock: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  authFetch: authFetchMock,
}));

vi.mock('@carbon/react', () => ({
  Button: ({ children, renderIcon: Icon, iconDescription, ...props }) => (
    <button aria-label={iconDescription} {...props}>
      {Icon ? <Icon /> : null}
      {children}
    </button>
  ),
  Loading: ({ description = 'Loading' }) => <div role="status">{description}</div>,
  InlineNotification: ({ title, subtitle }) => (
    <div role="alert">{title}: {subtitle}</div>
  ),
  Tag: ({ children }) => <span>{children}</span>,
}));

vi.mock('@carbon/react/icons', () => ({
  Renew: () => <span aria-hidden="true">renew</span>,
}));

import LogViewer from './LogViewer';

const apiResponse = (logs) => ({
  ok: true,
  json: async () => ({ logs }),
});

const application = (status, validationComments = '') => ({
  app_id_str: 'app_123',
  applicant_name: 'Tom Miller',
  loan_type: 'Home Renovation',
  amount: 50000,
  status,
  validation_comments: validationComments,
  submitted_date: '2026-09-01',
});

const log = (stage, data, timestamp) => ({ stage, data, timestamp });

describe('LogViewer application outcomes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('leads with a passed result and keeps raw tool data collapsed', async () => {
    authFetchMock.mockResolvedValue(apiResponse([
      log('invoke_agent', 'Invoking Document Processor Agent', '2026-09-01T06:15:34Z'),
      log('tool_call', '[{"name":"classify_document"}]', '2026-09-01T06:15:39Z'),
      log('agent_response', '{"documents":[]}', '2026-09-01T06:16:51Z'),
      log('invoke_agent', 'Invoking Document Validator Agent', '2026-09-01T06:16:52Z'),
      log('agent_response', '{"valid":true}', '2026-09-01T06:17:10Z'),
      log('invoke_agent', 'Invoking Final Decision Agent', '2026-09-01T06:17:11Z'),
      log('agent_response', '{"loan_application_status":"passed"}', '2026-09-01T06:17:30Z'),
    ]));

    render(
      <LogViewer
        application={application(
          'passed',
          '- **overall_validation_summary**: All validation checks passed successfully'
        )}
      />
    );

    expect(await screen.findByText('Validation passed')).toBeVisible();
    expect(screen.getByText('All validation checks passed successfully')).toBeVisible();
    expect(screen.getByLabelText('Document processing: Complete')).toBeVisible();
    expect(screen.getByLabelText('Document validation: Complete')).toBeVisible();
    expect(screen.getByLabelText('Final decision: Complete')).toBeVisible();

    const technicalDetails = screen.getByText('Technical details').closest('details');
    expect(technicalDetails).not.toHaveAttribute('open');
    expect(within(technicalDetails).getByText(/classify_document/)).not.toBeVisible();
  });

  it('shows a rejected decision as a completed business result, not an agent failure', async () => {
    authFetchMock.mockResolvedValue(apiResponse([
      log('invoke_agent', 'Invoking Document Processor Agent', '2026-09-01T06:36:15Z'),
      log('agent_response', '{"document_type":"Passport"}', '2026-09-01T06:36:32Z'),
      log('invoke_agent', 'Invoking Document Validator Agent', '2026-09-01T06:38:10Z'),
      log('agent_response', '{"valid":false}', '2026-09-01T06:39:37Z'),
      log('invoke_agent', 'Invoking Final Decision Agent', '2026-09-01T06:39:38Z'),
      log('agent_response', '{"loan_application_status":"rejected"}', '2026-09-01T06:39:45Z'),
    ]));

    render(
      <LogViewer
        application={application(
          'rejected',
          '- **overall_validation_summary**: Documents failed authenticity checks'
        )}
      />
    );

    expect(await screen.findByText('Application rejected')).toBeVisible();
    expect(screen.getByText('Documents failed authenticity checks')).toBeVisible();
    expect(screen.getByLabelText('Final decision: Complete')).toBeVisible();
  });

  it('identifies the failed agent and leaves later agents not started', async () => {
    authFetchMock.mockResolvedValue(apiResponse([
      log('invoke_agent', 'Invoking Document Processor Agent', '2026-09-01T03:19:13Z'),
      log('tool_call', '[{"name":"classify_document"}]', '2026-09-01T03:19:20Z'),
      log('agent_response', 'I have encountered an error. Please try again.', '2026-09-01T03:19:25Z'),
    ]));

    render(
      <LogViewer
        application={application(
          'Processing Failed',
          '- **error**: Application processing failed. Please retry.'
        )}
      />
    );

    expect(await screen.findByText('Processing failed')).toBeVisible();
    expect(screen.getByText('Application processing failed. Please retry.')).toBeVisible();
    expect(screen.getByLabelText('Document processing: Failed')).toBeVisible();
    expect(screen.getByLabelText('Document validation: Not started')).toBeVisible();
    expect(screen.getByLabelText('Final decision: Not started')).toBeVisible();
  });

  it('distinguishes an active retry from a terminal failure', async () => {
    authFetchMock.mockResolvedValue(apiResponse([
      log('invoke_agent', 'Invoking Document Validator Agent', '2026-09-01T06:07:40Z'),
      log('retry', { attempt: 2, reason: 'Temporary WXO interruption' }, '2026-09-01T06:08:17Z'),
    ]));

    render(
      <LogViewer
        application={application(
          'Retrying',
          '- **status**: Temporary agent interruption; retrying attempt 2 of 3.'
        )}
      />
    );

    expect(await screen.findByText('Temporary interruption')).toBeVisible();
    expect(screen.getByLabelText('Document validation: Retrying')).toBeVisible();
  });

  it('separates repeated processing attempts and handles empty history', async () => {
    const repeatedLogs = [
      log('invoke_agent', 'Invoking Document Processor Agent', '2026-09-01T06:24:42Z'),
      log('agent_response', '{"documents":[]}', '2026-09-01T06:25:09Z'),
      log('invoke_agent', 'Invoking Final Decision Agent', '2026-09-01T06:27:36Z'),
      log('agent_response', 'Incomplete final response', '2026-09-01T06:28:07Z'),
      log('invoke_agent', 'Invoking Document Processor Agent', '2026-09-01T06:30:46Z'),
      log('agent_response', '{"documents":[]}', '2026-09-01T06:31:15Z'),
    ];
    authFetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/applications/app_123')) {
        return { ok: true, json: async () => application('Processing Failed') };
      }
      return apiResponse(repeatedLogs);
    });

    const { unmount } = render(
      <LogViewer application={application('Processing Failed')} />
    );

    expect(await screen.findByText('Run 1')).toBeVisible();
    expect(screen.getByText('Run 2')).toBeVisible();

    unmount();
    authFetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/applications/app_123')) {
        return { ok: true, json: async () => application('Pending') };
      }
      return apiResponse([]);
    });
    render(<LogViewer application={application('Pending')} />);

    expect(await screen.findByText('No processing history yet')).toBeVisible();
  });

  it('refreshes application and logs while active, then stops at a final result', async () => {
    vi.useFakeTimers();
    const onApplicationChange = vi.fn();
    let applicationRequests = 0;

    authFetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/applications/app_123')) {
        applicationRequests += 1;
        return {
          ok: true,
          json: async () => application(
            applicationRequests === 1 ? 'Processing' : 'passed',
            applicationRequests === 1
              ? ''
              : '- **overall_validation_summary**: Retry completed successfully'
          ),
        };
      }
      return apiResponse([
        log('invoke_agent', 'Invoking Document Processor Agent', '2026-09-01T06:15:34Z'),
        log('agent_response', '{"documents":[]}', '2026-09-01T06:16:51Z'),
      ]);
    });

    render(
      <LogViewer
        application={application('Processing')}
        onApplicationChange={onApplicationChange}
      />
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText('Processing application')).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText('Validation passed')).toBeVisible();
    expect(screen.getByText('Retry completed successfully')).toBeVisible();
    expect(onApplicationChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'passed' })
    );

    const callsAtCompletion = authFetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(authFetchMock).toHaveBeenCalledTimes(callsAtCompletion);
  });

  it('retries a processing failure and immediately switches to the queued result', async () => {
    const queuedApplication = application(
      'Pending',
      '- **status**: Retry requested. Waiting for agent processing.'
    );
    const onApplicationChange = vi.fn();
    let retryRequested = false;

    authFetchMock.mockImplementation(async (url, options = {}) => {
      if (url.endsWith('/retry') && options.method === 'POST') {
        retryRequested = true;
        return { ok: true, json: async () => queuedApplication };
      }
      if (url.endsWith('/applications/app_123')) {
        return {
          ok: true,
          json: async () => retryRequested
            ? queuedApplication
            : application(
              'Processing Failed',
              '- **error**: Application processing failed. Please retry.'
            ),
        };
      }
      return apiResponse([]);
    });

    render(
      <LogViewer
        application={application(
          'Processing Failed',
          '- **error**: Application processing failed. Please retry.'
        )}
        onApplicationChange={onApplicationChange}
      />
    );

    const retryButton = await screen.findByRole('button', { name: 'Retry processing' });
    await waitFor(() => expect(retryButton).toBeEnabled());
    fireEvent.click(retryButton);

    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/applications/app_123/retry',
      { method: 'POST' }
    ));
    expect(await screen.findByText('Waiting to start')).toBeVisible();
    expect(onApplicationChange).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'Pending' })
    );
  });
});
