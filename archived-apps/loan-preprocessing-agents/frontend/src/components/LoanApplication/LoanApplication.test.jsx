import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { authFetchMock } = vi.hoisted(() => ({
  authFetchMock: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  authFetch: authFetchMock,
}));

const { useSystemStatusMock } = vi.hoisted(() => ({ useSystemStatusMock: vi.fn() }));
vi.mock('../../contexts/useSystemStatus', () => ({
  useSystemStatus: useSystemStatusMock,
}));

vi.mock('../CapabilityNotice/CapabilityNotice', () => ({ default: ({ capabilityIds }) => (
  <div data-testid="capability-notice" data-capability-ids={capabilityIds.join(',')} />
)}));

/* The notice is mocked at this integration boundary so the page contract and DOM placement are explicit. */
const defaultStatus = {
  status: { capabilities: [] },
  isLoading: false,
};

beforeEach(() => {
  useSystemStatusMock.mockReturnValue(defaultStatus);
});

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
  TextInput: ({ id, labelText, value, onChange, type, invalidText, helperText }) => (
    <label htmlFor={id}>{labelText}<input id={id} value={value} onChange={onChange} type={type} />{helperText}<span>{invalidText}</span></label>
  ),
  Select: ({ id, labelText, children, value, onChange }) => (
    <label htmlFor={id}>{labelText}<select id={id} value={value} onChange={onChange}>{children}</select></label>
  ),
  SelectItem: ({ text, ...props }) => <option {...props}>{text}</option>,
  NumberInput: ({ id, label, value, onChange, min, invalidText, helperText }) => (
    <label htmlFor={id}>{label}<input id={id} type="number" value={value} onChange={onChange} min={min} />{helperText}<span>{invalidText}</span></label>
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
  Modal: ({ open, modalHeading, primaryButtonText, children, onRequestSubmit }) => open ? (
    <section role="dialog" aria-label={modalHeading}>{children}<button onClick={onRequestSubmit}>{primaryButtonText}</button></section>
  ) : null,
  Loading: () => <span role="status">Loading</span>,
  FileUploader: ({ labelDescription, accept, multiple, onChange, buttonLabel, iconDescription }) => (
    <label>{buttonLabel}<input aria-label={labelDescription} title={iconDescription} type="file" accept={accept} multiple={multiple} onChange={onChange} /></label>
  ),
  Tile: ({ children, onClick }) => <div role="button" tabIndex="0" onClick={onClick}>{children}</div>,
  InlineNotification: ({ title, subtitle }) => <div>{title} {subtitle}</div>,
}));

import LoanApplication from './LoanApplication';
import i18n from '../../i18n/config';

const jsonResponse = (data) => ({
  ok: true,
  status: 200,
  json: async () => data,
});

const fixtureManifestResponse = (url) => ({
  ok: true,
  status: 200,
  json: async () => {
    const scenario = url.includes('/reject/') ? 'reject' : 'pass';
    return {
      scenario,
      files: {
        applicationPdf: { filename: `demo-${scenario}-Loan-Application-Form.pdf`, content_type: 'application/pdf' },
        idProof: { filename: `demo-${scenario}-ID-Doc.png`, content_type: 'image/png' },
        incomeProof: { filename: `demo-${scenario}-Income-Doc.png`, content_type: 'image/png' },
        addressProof: { filename: `demo-${scenario}-Address-Doc.png`, content_type: 'image/png' },
        ssn: { filename: `demo-${scenario}-SSN.png`, content_type: 'image/png' },
      },
    };
  },
});

describe('LoanApplication POC presets', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en-US');
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8000');
    authFetchMock.mockImplementation(async (url, options = {}) => {
      if (url.endsWith('/users/me')) {
        return jsonResponse({
          first_name: 'Tom',
          last_name: 'Miller',
          date_of_birth: '1980-01-21',
        });
      }
      if (url.endsWith('/manifest') && url.includes('/demo_fixtures/')) {
        return fixtureManifestResponse(url);
      }
      if (options.method === 'POST') {
        return jsonResponse({ application_id: 'app-demo-1' });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  it('requests all Apply capabilities and places the notice after the heading', () => {
    render(<LoanApplication />);
    const heading = screen.getByRole('heading', { name: 'Choose Your Application Method' });
    const notice = screen.getByTestId('capability-notice');
    expect(notice).toHaveAttribute('data-capability-ids', 'submit_application,process_documents,generate_decision');
    expect(heading.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(notice.compareDocumentPosition(screen.getByText('Fill Application Form')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
      const submitCall = authFetchMock.mock.calls.find(([url]) => url.endsWith('/submit_demo_form'));
      expect(submitCall).toBeDefined();
      expect(submitCall[1].body.get('demoScenario')).toBe('pass');
      expect([...submitCall[1].body.values()].some((value) => value instanceof File)).toBe(false);
    });
    expect(
      authFetchMock.mock.calls.filter(([url]) => url.includes('/demo_fixtures/'))
    ).toHaveLength(1);
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

    fireEvent.click(screen.getByRole('button', { name: 'Submit Application' }));
    await waitFor(() => {
      const submitCall = authFetchMock.mock.calls.find(([url]) => url.endsWith('/submit_demo_pdf'));
      expect(submitCall).toBeDefined();
      expect(submitCall[1].body.get('demoScenario')).toBe('reject');
      expect([...submitCall[1].body.values()].some((value) => value instanceof File)).toBe(false);
    });
  });

  it('ignores a slow preset response after the user changes method', async () => {
    const pendingFixtures = [];
    authFetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/users/me')) {
        return jsonResponse({ first_name: 'Tom', last_name: 'Miller' });
      }
      if (url.endsWith('/manifest') && url.includes('/demo_fixtures/')) {
        return new Promise((resolve) => {
          pendingFixtures.push(() => resolve(fixtureManifestResponse(url)));
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
      if (url.endsWith('/manifest') && url.includes('/demo_fixtures/')) {
        return fixtureManifestResponse(url);
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

  it.each([
    ['zh-TW', '選擇申請方式', '線上填寫申請表', '載入通過範例', '個人資料'],
    ['zh-CN', '选择申请方式', '在线填写申请表', '加载通过示例', '个人信息'],
    ['en-US', 'Choose Your Application Method', 'Fill Application Form', 'Load Pass example', 'Personal Information'],
    ['en-GB', 'Choose Your Application Method', 'Fill Application Form', 'Load Pass example', 'Personal Information'],
  ])('localizes representative Apply controls for %s', async (locale, methodHeading, formMethod, passPreset, personalStep) => {
    await i18n.changeLanguage(locale);
    render(<LoanApplication />);

    expect(screen.getByRole('heading', { name: methodHeading })).toBeVisible();
    fireEvent.click(screen.getByText(formMethod));

    expect(screen.getByRole('heading', { name: personalStep })).toBeVisible();
    expect(screen.getByRole('button', { name: passPreset })).toBeVisible();
  });

  it('localizes validation, PDF upload, review, submission, and success UI in zh-TW', async () => {
    await i18n.changeLanguage('zh-TW');
    render(<LoanApplication />);

    fireEvent.click(screen.getByText('線上填寫申請表'));
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByText('名字為必填')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '變更申請方式' }));
    fireEvent.click(screen.getByText('上傳已填寫的 PDF'));
    expect(screen.getByRole('heading', { name: '上傳申請 PDF' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByText('必須上傳申請 PDF')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '載入拒絕範例' }));
    expect(await screen.findByRole('heading', { name: '檢查您的申請' })).toBeVisible();
    expect(screen.getByText('必要同意事項')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '送出申請' }));
    expect(await screen.findByRole('dialog', { name: '申請已成功送出' })).toBeVisible();
  });

  it('submits identical Pass multipart entries in all four locales', async () => {
    const methodLabels = {
      'zh-TW': '線上填寫申請表',
      'zh-CN': '在线填写申请表',
      'en-US': 'Fill Application Form',
      'en-GB': 'Fill Application Form',
    };
    const presetLabels = {
      'zh-TW': '載入通過範例',
      'zh-CN': '加载通过示例',
      'en-US': 'Load Pass example',
      'en-GB': 'Load Pass example',
    };
    const submitLabels = {
      'zh-TW': '送出申請',
      'zh-CN': '提交申请',
      'en-US': 'Submit Application',
      'en-GB': 'Submit Application',
    };
    const snapshots = [];

    for (const locale of Object.keys(methodLabels)) {
      authFetchMock.mockClear();
      await i18n.changeLanguage(locale);
      const view = render(<LoanApplication />);
      fireEvent.click(screen.getByText(methodLabels[locale]));
      fireEvent.click(screen.getByRole('button', { name: presetLabels[locale] }));
      await screen.findByText('Tom Miller');
      fireEvent.click(screen.getByRole('button', { name: submitLabels[locale] }));

      await waitFor(() => {
        expect(authFetchMock.mock.calls.some(([url]) => url.endsWith('/submit_demo_form'))).toBe(true);
      });
      const [, options] = authFetchMock.mock.calls.find(([url]) => url.endsWith('/submit_demo_form'));
      snapshots.push([...options.body.entries()].map(([key, value]) => [
        key,
        value instanceof File ? value.name : value,
      ]));
      view.unmount();
      cleanup();
    }

    snapshots.slice(1).forEach((snapshot) => expect(snapshot).toEqual(snapshots[0]));
    const formData = JSON.parse(snapshots[0].find(([key]) => key === 'formDataJson')[1]);
    expect(formData.employmentStatus).toBe('employed');
    expect(formData.creditScore).toBe('good');
    expect(formData.loanType).toBe('Home Renovation');
  });

  it('keeps Reject preset enum values unchanged', async () => {
    render(<LoanApplication />);
    fireEvent.click(screen.getByText('Fill Application Form'));
    fireEvent.click(screen.getByRole('button', { name: 'Load Reject example' }));
    await screen.findByText('Jordan Example');
    fireEvent.click(screen.getByRole('button', { name: 'Submit Application' }));

    await waitFor(() => {
      expect(authFetchMock.mock.calls.some(([url]) => url.endsWith('/submit_demo_form'))).toBe(true);
    });
    const [, options] = authFetchMock.mock.calls.find(([url]) => url.endsWith('/submit_demo_form'));
    const submitted = JSON.parse(options.body.get('formDataJson'));
    expect(submitted.employmentStatus).toBe('employed');
    expect(submitted.loanType).toBe('Personal');
    expect(submitted.creditScore).toBe('poor');
  });
});
