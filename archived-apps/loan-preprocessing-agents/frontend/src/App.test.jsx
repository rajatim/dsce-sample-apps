import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

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
  return <output aria-label="Current path">{location.pathname}</output>;
};

describe('App demo-only routes', () => {
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
});
