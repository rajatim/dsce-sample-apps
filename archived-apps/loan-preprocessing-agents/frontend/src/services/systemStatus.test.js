import { beforeEach, describe, expect, it, vi } from 'vitest';

const { authFetchMock } = vi.hoisted(() => ({ authFetchMock: vi.fn() }));

vi.mock('./api', () => ({ authFetch: authFetchMock }));

import { fetchSystemStatus } from './systemStatus';

const validStatus = {
  overall: { status: 'ready', title: 'Ready', message: 'All systems are ready.' },
  checked_at: '2026-09-04T00:00:00Z',
  stale_after_seconds: 300,
  stale: false,
  capabilities: [{ id: 'view_applications', label: 'View applications', status: 'ready', message: 'Ready' }],
  dependencies: [{ id: 'postgresql', label: 'PostgreSQL', status: 'ready', evidence: 'live_check', message: 'Ready' }],
};

const jsonResponse = (payload, options = {}) => ({
  ok: options.ok ?? true,
  status: options.status ?? 200,
  json: async () => payload,
});

describe('fetchSystemStatus', () => {
  beforeEach(() => {
    authFetchMock.mockReset();
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
  });

  it('requests the public status endpoint without refresh by default', async () => {
    authFetchMock.mockResolvedValue(jsonResponse(validStatus));
    await fetchSystemStatus();
    expect(authFetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/system-status',
      expect.objectContaining({ signal: undefined }),
    );
  });

  it('uses refresh=true only for a manual refresh', async () => {
    authFetchMock.mockResolvedValue(jsonResponse(validStatus));
    await fetchSystemStatus({ refresh: true });
    expect(authFetchMock.mock.calls[0][0]).toContain('/system-status?refresh=true');
  });

  it.each([
    ['non-2xx', jsonResponse({ detail: 'secret server failure' }, { ok: false, status: 500 })],
    ['malformed payload', jsonResponse({ overall: { status: 'secret' } })],
  ])('returns one safe error for %s', async (_name, response) => {
    authFetchMock.mockResolvedValue(response);
    await expect(fetchSystemStatus()).rejects.toThrow('Demo status is currently unavailable.');
    await expect(fetchSystemStatus()).rejects.not.toThrow('secret');
  });

  it('rejects unknown statuses and non-array collections', async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ ...validStatus, overall: { ...validStatus.overall, status: 'secret' }, capabilities: {} }));
    await expect(fetchSystemStatus()).rejects.toThrow('Demo status is currently unavailable.');
  });
});
