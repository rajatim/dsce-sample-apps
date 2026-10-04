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
    authFetchMock.mockImplementation((url) => {
      if (url !== 'http://127.0.0.1:8000/system-status'
        && url !== 'http://127.0.0.1:8000/system-status?refresh=true') {
        throw new Error(`unexpected URL: ${url}`);
      }
      return Promise.resolve(jsonResponse(validStatus));
    });
  });

  it('requests the public status endpoint without refresh by default', async () => {
    await fetchSystemStatus();
    expect(authFetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/system-status',
      expect.objectContaining({ signal: undefined }),
    );
  });

  it('uses refresh=true only for a manual refresh', async () => {
    await fetchSystemStatus({ refresh: true });
    expect(authFetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/system-status?refresh=true');
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

  it('requests only the selected dependency on a manual check', async () => {
    authFetchMock.mockResolvedValue(jsonResponse(validStatus));
    await fetchSystemStatus({ refresh: true, dependency: 'cos' });
    expect(authFetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/system-status?refresh=true&dependency=cos');
  });

  it('rejects malformed diagnostic fields', async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ ...validStatus, dependencies: [{
      ...validStatus.dependencies[0], problem: { http_status: 'private-body' },
    }] }));
    await expect(fetchSystemStatus()).rejects.toThrow('Demo status is currently unavailable.');
  });

  it('passes the caller signal through unchanged', async () => {
    const signal = new AbortController().signal;
    await fetchSystemStatus({ signal });
    expect(authFetchMock.mock.calls[0][1].signal).toBe(signal);
  });

  const authentication = {
    token_status: 'succeeded', checked_at: '2026-10-04T07:20:37Z',
    api_key_expiry_status: 'unknown', api_key_expires_at: null,
    key_management_available: false, key_management_reason: 'expiry_and_admin_access_unverified',
  };
  const wxoResponse = (auth) => jsonResponse({ ...validStatus, dependencies: [{
    ...validStatus.dependencies[0], id: 'wxo', authentication: auth,
  }] });

  it.each(['succeeded', 'failed', 'not_checked'])('keeps the safe %s authentication result', async (token_status) => {
    const auth = { ...authentication, token_status, checked_at: token_status === 'not_checked' ? null : authentication.checked_at };
    authFetchMock.mockResolvedValue(wxoResponse(auth));
    const result = await fetchSystemStatus({ refresh: true, dependency: 'wxo' });
    expect(result.dependencies[0].authentication).toEqual(auth);
    expect(authFetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/system-status?refresh=true&dependency=wxo');
  });

  it.each([
    undefined, null, {}, 'invalid',
    { ...authentication, token_status: 'expired' },
    { ...authentication, checked_at: 'not-a-date' },
    { ...authentication, checked_at: null },
    { ...authentication, api_key_expiry_status: 'expired' },
    { ...authentication, api_key_expires_at: '2026-10-04T07:20:00Z' },
    { ...authentication, key_management_available: true },
    { ...authentication, key_management_reason: 'unknown-policy' },
    { ...authentication, token: 'never-forward-this' },
  ])('keeps status usable with unsupported authentication metadata (%j)', async (auth) => {
    authFetchMock.mockResolvedValue(wxoResponse(auth));
    const result = await fetchSystemStatus();
    expect(result.overall.status).toBe('ready');
    expect(result.dependencies[0].authentication).toBeNull();
  });
});
