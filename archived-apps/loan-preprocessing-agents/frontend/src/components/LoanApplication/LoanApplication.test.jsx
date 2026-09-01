import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { authFetchMock } = vi.hoisted(() => ({
  authFetchMock: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  authFetch: authFetchMock,
}));

vi.mock('@carbon/react/icons', () => ({
  User: () => null,
  Settings: () => null,
  Help: () => null,
  DocumentPdf: () => null,
  Document: () => null,
}));

vi.mock('@carbon/react', () => ({
  Button: ({ children, onClick, disabled }) => (
    <button onClick={onClick} disabled={disabled}>{children}</button>
  ),
  TextInput: ({ id, labelText, value, onChange, type }) => (
    <label htmlFor={id}>{labelText}<input id={id} value={value} onChange={onChange} type={type} /></label>
  ),
  Select: ({ id, labelText, children, value, onChange }) => (
    <label htmlFor={id}>{labelText}<select id={id} value={value} onChange={onChange}>{children}</select></label>
  ),
  SelectItem: ({ text, ...props }) => <option {...props}>{text}</option>,
  NumberInput: ({ id, label, value, onChange, min }) => (
    <label htmlFor={id}>{label}<input id={id} type="number" value={value} onChange={onChange} min={min} /></label>
  ),
  DatePicker: ({ children }) => <div>{children}</div>,
  DatePickerInput: ({ id, labelText, placeholder }) => (
    <label htmlFor={id}>{labelText}<input id={id} placeholder={placeholder} /></label>
  ),
  Checkbox: ({ id, labelText, checked, onChange }) => (
    <label htmlFor={id}><input id={id} type="checkbox" checked={checked} onChange={onChange} />{labelText}</label>
  ),
  RadioButton: ({ labelText, ...props }) => <label><input type="radio" {...props} />{labelText}</label>,
  RadioButtonGroup: ({ children }) => <div>{children}</div>,
  ProgressIndicator: ({ children }) => <div>{children}</div>,
  ProgressStep: ({ label }) => <span>{label}</span>,
  FormGroup: ({ legendText, children }) => <fieldset><legend>{legendText}</legend>{children}</fieldset>,
  Heading: ({ children }) => <h2>{children}</h2>,
  Section: ({ children }) => <section>{children}</section>,
  Modal: () => null,
  Loading: () => <span role="status">Loading</span>,
  FileUploader: ({ labelDescription, accept, multiple, onChange }) => (
    <input aria-label={labelDescription} type="file" accept={accept} multiple={multiple} onChange={onChange} />
  ),
  Tile: ({ children, onClick }) => <div role="button" tabIndex="0" onClick={onClick}>{children}</div>,
  InlineNotification: ({ title, subtitle }) => <div>{title} {subtitle}</div>,
}));

import LoanApplication from './LoanApplication';

const jsonResponse = (data) => ({
  ok: true,
  status: 200,
  json: async () => data,
});

const fixtureResponse = (url) => ({
  ok: true,
  status: 200,
  blob: async () => new Blob(
    [url.includes('applicationPdf') ? '%PDF fixture' : 'image fixture'],
    { type: url.includes('applicationPdf') ? 'application/pdf' : 'image/png' }
  ),
});

describe('LoanApplication POC presets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
    authFetchMock.mockImplementation(async (url, options = {}) => {
      if (url.endsWith('/users/me')) {
        return jsonResponse({
          first_name: 'Tom',
          last_name: 'Miller',
          date_of_birth: '1980-01-21',
        });
      }
      if (url.includes('/demo_fixtures/')) {
        return fixtureResponse(url);
      }
      if (options.method === 'POST') {
        return jsonResponse({ application_id: 'app-demo-1' });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  it('loads the Pass form preset, jumps to review, and submits its scenario', async () => {
    render(<LoanApplication />);
    fireEvent.click(screen.getByText('Fill Application Form'));

    fireEvent.click(screen.getByRole('button', { name: 'Load Pass example' }));

    expect(await screen.findByText('Review Your Application')).toBeVisible();
    expect(screen.getByText('Tom Miller')).toBeVisible();
    expect(screen.getByText('demo-pass-ID-Doc.png')).toBeVisible();
    expect(screen.getByText('demo-pass-SSN.png')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'Submit Application' }));

    await waitFor(() => {
      const submitCall = authFetchMock.mock.calls.find(([url]) => url.endsWith('/submit_form'));
      expect(submitCall).toBeDefined();
      expect(submitCall[1].body.get('demoScenario')).toBe('pass');
    });
  });

  it('loads all files for the Reject PDF preset and jumps to review', async () => {
    render(<LoanApplication />);
    fireEvent.click(screen.getByText('Upload Filled PDF'));

    fireEvent.click(screen.getByRole('button', { name: 'Load Reject example' }));

    expect(await screen.findByText('Review Your Application')).toBeVisible();
    expect(screen.getByText('demo-reject-Loan-Application-Form.pdf')).toBeVisible();
    expect(screen.getByText('demo-reject-ID-Doc.png')).toBeVisible();
    expect(screen.getByText('demo-reject-Income-Doc.png')).toBeVisible();
    expect(screen.getByText('demo-reject-Address-Doc.png')).toBeVisible();
  });

  it('ignores a slow preset response after the user changes method', async () => {
    const pendingFixtures = [];
    authFetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/users/me')) {
        return jsonResponse({ first_name: 'Tom', last_name: 'Miller' });
      }
      if (url.includes('/demo_fixtures/')) {
        return new Promise((resolve) => {
          pendingFixtures.push(() => resolve(fixtureResponse(url)));
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LoanApplication />);
    fireEvent.click(screen.getByText('Fill Application Form'));
    fireEvent.click(screen.getByRole('button', { name: 'Load Pass example' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change Method' }));

    pendingFixtures.forEach((resolveFixture) => resolveFixture());
    await waitFor(() => {
      expect(screen.getByText('Choose Your Application Method')).toBeVisible();
    });
    expect(screen.queryByText('Review Your Application')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Fill Application Form'));
    expect(screen.getByRole('heading', { name: 'Personal Information' })).toBeVisible();
    expect(screen.queryByText('Pass POC example loaded')).not.toBeInTheDocument();
  });

  it('does not let a slow user prefill overwrite a loaded demo preset', async () => {
    let resolveUser;
    authFetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/users/me')) {
        return new Promise((resolve) => {
          resolveUser = resolve;
        });
      }
      if (url.includes('/demo_fixtures/')) {
        return fixtureResponse(url);
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LoanApplication />);
    fireEvent.click(screen.getByText('Fill Application Form'));
    fireEvent.click(screen.getByRole('button', { name: 'Load Pass example' }));
    expect(await screen.findByText('Tom Miller')).toBeVisible();

    resolveUser(jsonResponse({
      first_name: 'Wrong',
      last_name: 'User',
      date_of_birth: '1999-12-31',
    }));
    await waitFor(() => {
      expect(screen.queryByText('Wrong User')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Tom Miller')).toBeVisible();
  });
});
