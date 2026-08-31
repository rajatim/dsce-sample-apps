import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loginMock, navigateMock } = vi.hoisted(() => ({
  loginMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ login: loginMock }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('@carbon/react', () => ({
  Form: ({ children, ...props }) => <form {...props}>{children}</form>,
  TextInput: ({ id, labelText, ...props }) => (
    <label htmlFor={id}>
      {labelText}
      <input id={id} {...props} />
    </label>
  ),
  PasswordInput: ({ id, labelText, ...props }) => (
    <label htmlFor={id}>
      {labelText}
      <input id={id} type="password" {...props} />
    </label>
  ),
  Button: ({ children, ...props }) => <button {...props}>{children}</button>,
  InlineLoading: ({ description }) => <div role="status">{description}</div>,
  InlineNotification: ({ title, subtitle }) => (
    <div role="alert">
      {title}: {subtitle}
    </div>
  ),
}));

import { LoginPage } from './LoginPage';

const renderLoginPage = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <LoginPage />
    </MemoryRouter>
  );

describe('LoginPage demo login', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
  });

  it('automatically signs in the demo user when launched with demo=1', async () => {
    let resolveRequest;
    const fetchMock = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve;
        })
    );
    vi.stubGlobal('fetch', fetchMock);

    renderLoginPage('/login?demo=1');

    expect(screen.getByRole('status')).toHaveTextContent('Entering demo');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:8000/token');
    expect(options.body.toString()).toBe('username=tom_miller&password=Pass1234');

    resolveRequest({
      ok: true,
      json: async () => ({ access_token: 'demo-access-token' }),
    });

    await waitFor(() => expect(loginMock).toHaveBeenCalledWith('demo-access-token'));
    expect(navigateMock).toHaveBeenCalledWith('/apply');
  });

  it('keeps the manual login form when demo mode is absent', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    renderLoginPage('/login');

    expect(screen.getByRole('textbox', { name: 'Username' })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('falls back to the manual form when automatic demo login fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Incorrect username or password' }),
      })
    );

    renderLoginPage('/login?demo=1');

    expect(
      await screen.findByText(
        'Login Error: Automatic demo login failed: Incorrect username or password'
      )
    ).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Username' })).toBeVisible();
  });
});
