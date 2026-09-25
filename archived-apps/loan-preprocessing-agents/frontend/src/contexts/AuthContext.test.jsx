import React, { StrictMode } from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from './AuthContext';
import { useAuth } from './useAuth';
import i18n from '../i18n/config';

const AuthState = () => {
  const { token } = useAuth();
  return <p>Demo token: {token}</p>;
};

describe('AuthProvider demo access', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
    const storage = new Map();
    vi.stubGlobal('localStorage', {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
      clear: () => storage.clear(),
    });
    localStorage.clear();
    vi.restoreAllMocks();
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
  });

  it('silently prepares one demo session without showing a login form', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: 'demo-access-token' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <StrictMode>
        <AuthProvider>
          <AuthState />
        </AuthProvider>
      </StrictMode>
    );

    expect(screen.getByText('Preparing the loan demo')).toBeVisible();
    expect(screen.queryByRole('textbox', { name: /username/i })).not.toBeInTheDocument();
    expect(await screen.findByText('Demo token: demo-access-token')).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:8000/token');
    expect(options.body.toString()).toBe('username=tom_miller&password=Pass1234');
  });

  it('shows a retryable service error instead of revealing the login screen', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Backend unavailable' }),
    }));

    render(
      <AuthProvider>
        <AuthState />
      </AuthProvider>
    );

    expect(await screen.findByText('Demo service unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible();
    expect(screen.queryByRole('textbox', { name: /username/i })).not.toBeInTheDocument();
  });

  it('localizes frontend access chrome while preserving a backend error body', async () => {
    await i18n.changeLanguage('zh-TW');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Backend unavailable' }),
    }));
    render(<AuthProvider><AuthState /></AuthProvider>);
    expect(await screen.findByRole('heading', { name: 'Demo 服務無法使用' })).toBeVisible();
    expect(screen.getByText('Backend unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: '再試一次' })).toBeVisible();
  });
});
