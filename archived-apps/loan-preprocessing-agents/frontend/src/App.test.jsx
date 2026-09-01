import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@carbon/react', () => ({
  Header: ({ children }) => <header>{children}</header>,
  HeaderName: (props) => React.createElement(props.as, { to: props.to }, props.children),
  HeaderNavigation: ({ children }) => <nav>{children}</nav>,
  HeaderMenuItem: (props) => React.createElement(props.as, { to: props.to }, props.children),
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
});
