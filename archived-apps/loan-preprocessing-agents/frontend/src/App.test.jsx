import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from './i18n/config';
import { LOCALE_STORAGE_KEY } from './i18n/locales';

vi.mock('@carbon/react', () => ({
  Header: ({ children }) => <header>{children}</header>,
  HeaderName: (props) => React.createElement(props.as, { to: props.to }, props.children),
  HeaderNavigation: ({ children }) => <nav>{children}</nav>,
  HeaderMenuItem: ({ as, children, ...props }) => React.createElement(as, props, children),
  HeaderMenuButton: ({ isActive, ...props }) => (
    <button {...props} aria-expanded={isActive} />
  ),
  SideNav: ({
    children,
    expanded,
    isPersistent,
    onOverlayClick,
    onSideNavBlur,
    ...props
  }) => {
    void isPersistent;
    void onOverlayClick;
    void onSideNavBlur;
    return <nav {...props} hidden={!expanded}>{children}</nav>;
  },
  SideNavItems: ({ children }) => <ul>{children}</ul>,
  SideNavLink: ({ as, children, ...props }) => React.createElement(as, props, children),
  HeaderGlobalBar: ({ children }) => <div>{children}</div>,
  HeaderGlobalAction: ({ children, ...props }) => <button {...props}>{children}</button>,
}));

vi.mock('@carbon/icons-react', () => ({
  ArrowLeft: () => <span aria-hidden="true">←</span>,
}));

vi.mock('./components/SidePanel/SidePanel', () => ({
  default: ({ children }) => <aside>{children}</aside>,
}));
vi.mock('./components/LoanApplication/LoanApplication', () => ({
  default: () => <h1>Loan application form</h1>,
}));
vi.mock('./components/MyApplications/MyApplications', () => ({
  default: () => <h1>My applications</h1>,
}));
vi.mock('./components/LoanCalculator/LoanCalculator', () => ({
  default: () => <h1>Loan calculator</h1>,
}));
vi.mock('./components/SystemStatus/SystemStatus', () => ({
  default: () => <h1>Demo status page</h1>,
}));
vi.mock('./contexts/SystemStatusContext', () => ({
  SystemStatusProvider: ({ children }) => <>{children}</>,
}));

import App from './App';

const CurrentPath = () => {
  const location = useLocation();
  return <output aria-label="Current path">{`${location.pathname}${location.search}`}</output>;
};

describe('App demo-only routes', () => {
  beforeEach(async () => {
    const storage = new Map();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: (key) => storage.delete(key),
        clear: () => storage.clear(),
      },
    });
    const sessionStorage = new Map();
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      value: {
        getItem: (key) => sessionStorage.get(key) ?? null,
        setItem: (key, value) => sessionStorage.set(key, String(value)),
        removeItem: (key) => sessionStorage.delete(key),
        clear: () => sessionStorage.clear(),
      },
    });
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: null,
    });
    vi.stubGlobal('fetch', vi.fn());
    await i18n.changeLanguage('en-US');
    document.documentElement.lang = 'en-US';
  });

  it.each(['/login', '/login?demo=1', '/register'])(
    'replaces obsolete auth route %s with the application',
    async (initialEntry) => {
      render(
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
          <CurrentPath />
        </MemoryRouter>
      );

      await waitFor(() => {
        expect(screen.getByLabelText('Current path')).toHaveTextContent('/apply');
      });
      expect(screen.getByText('Loan application form')).toBeVisible();
      expect(screen.queryByText('Login')).not.toBeInTheDocument();
      expect(screen.queryByText('Register')).not.toBeInTheDocument();
    }
  );

  it('keeps all primary destinations available from the mobile navigation', async () => {
    render(
      <MemoryRouter initialEntries={['/apply']}>
        <App />
        <CurrentPath />
      </MemoryRouter>
    );

    const menuButton = screen.getByRole('button', { name: 'Open navigation menu' });
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('mobile-navigation')).not.toBeVisible();

    fireEvent.click(menuButton);

    expect(screen.getByRole('button', { name: 'Close navigation menu' })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByRole('navigation', { name: 'Mobile navigation' })).toBeVisible();

    fireEvent.click(screen.getAllByRole('link', { name: 'My Applications' }).at(-1));

    await waitFor(() => {
      expect(screen.getByLabelText('Current path')).toHaveTextContent('/my-applications');
    });
    expect(screen.getByRole('button', { name: 'Open navigation menu' })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
  });

  it('exposes Demo status in desktop and mobile navigation and closes the mobile drawer', async () => {
    render(
      <MemoryRouter initialEntries={['/apply']}>
        <App />
        <CurrentPath />
      </MemoryRouter>
    );

    expect(screen.getByRole('link', { name: 'Demo status' })).toHaveAttribute('href', '/status');
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation menu' }));

    const statusLinks = screen.getAllByRole('link', { name: 'Demo status' });
    expect(statusLinks).toHaveLength(2);
    fireEvent.click(statusLinks.at(-1));

    await waitFor(() => {
      expect(screen.getByLabelText('Current path')).toHaveTextContent('/status');
    });
    expect(screen.getByRole('button', { name: 'Open navigation menu' })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    expect(screen.getByText('Demo status page')).toBeVisible();
  });

  it('renders the Demo status page at /status without removing navigation', () => {
    render(
      <MemoryRouter initialEntries={['/status']}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText('Demo status page')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Apply' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Demo status' })).toBeVisible();
  });

  it('closes the mobile navigation with Escape', () => {
    render(
      <MemoryRouter initialEntries={['/apply']}>
        <App />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open navigation menu' }));
    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.getByRole('button', { name: 'Open navigation menu' })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
  });

  it('localizes visible navigation and preserves the current route query', async () => {
    render(
      <MemoryRouter initialEntries={['/apply?demo=1&lang=en-US']}>
        <App />
        <CurrentPath />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getAllByRole('combobox', { name: 'Language' })[0], {
      target: { value: 'zh-TW' },
    });

    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: '申請' }).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByRole('link', { name: '我的申請' }).length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Current path')).toHaveTextContent(
      '/apply?demo=1&lang=zh-TW',
    );
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-TW');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('keeps a language selector inside the expanded mobile navigation', () => {
    render(
      <MemoryRouter initialEntries={['/apply?lang=en-US']}>
        <App />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open navigation menu' }));
    const mobileNavigation = screen.getByRole('navigation', { name: 'Mobile navigation' });
    expect(mobileNavigation.querySelector('select')).toHaveAccessibleName('Language');
  });

  it('keeps a trusted DSCE return destination available in desktop and mobile navigation', async () => {
    await i18n.changeLanguage('zh-TW');
    const returnTo = 'http://localhost:3000/dsce/zh-TW/wizard/watsonx/results/watsonx-loan-preprocessing-agents';

    render(
      <MemoryRouter initialEntries={[`/apply?lang=zh-TW&returnTo=${encodeURIComponent(returnTo)}`]}>
        <App />
        <CurrentPath />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('link', { name: '返回 DSCE 展示台' })).toHaveAttribute(
      'href',
      returnTo,
    );

    fireEvent.click(screen.getByRole('button', { name: '開啟導覽選單' }));
    expect(screen.getAllByRole('link', { name: '返回 DSCE 展示台' })).toHaveLength(2);

    fireEvent.click(screen.getAllByRole('link', { name: '我的申請' }).at(-1));
    await waitFor(() => {
      expect(screen.getByLabelText('Current path')).toHaveTextContent('/my-applications');
    });
    expect(screen.getByRole('link', { name: '返回 DSCE 展示台' })).toHaveAttribute(
      'href',
      returnTo,
    );
  });

  it('focuses the DSCE opener and closes a script-opened Loan tab', async () => {
    const focus = vi.fn();
    const close = vi.spyOn(window, 'close').mockImplementation(() => {});
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { closed: false, focus },
    });

    render(
      <MemoryRouter initialEntries={['/apply?returnTo=http%3A%2F%2Flocalhost%3A3000%2Fdsce%2Fwatsonx']}>
        <App />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('link', { name: 'Back to DSCE showcase' }));
    expect(focus).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
  });

  it('does not expose an untrusted return destination', async () => {
    render(
      <MemoryRouter initialEntries={['/apply?returnTo=https%3A%2F%2Fevil.example%2Fdsce%2Fwatsonx']}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('link', { name: 'Back to DSCE showcase' })).toHaveAttribute(
      'href',
      'http://localhost:3000/dsce/watsonx',
    );
  });
});
