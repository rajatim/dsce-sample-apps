import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildApiUrl } from './apiBaseUrl';

describe('buildApiUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('uses the same-origin /api proxy by default', () => {
    vi.stubEnv('VITE_API_URL', '');

    expect(buildApiUrl('/token')).toBe('/api/token');
  });

  it('normalizes a configured API base URL', () => {
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000/');

    expect(buildApiUrl('/users/me')).toBe('http://127.0.0.1:8000/users/me');
  });
});
