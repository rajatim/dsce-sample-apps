import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../../i18n/config';
import { formatUsd } from '../../i18n/format';

vi.mock('@carbon/react', () => ({
  Form: (props) => <form {...props} />,
  NumberInput: ({ id, label, value, onChange, invalidText }) => (
    <label htmlFor={id}>{label}<input aria-label={label} id={id} type="number" value={value} aria-errormessage={`${id}-error`} onChange={(event) => onChange(event, { value: event.target.value })} /><span id={`${id}-error`}>{invalidText}</span></label>
  ),
  Button: ({ children, renderIcon: Icon, ...props }) => <button {...props}>{Icon ? <Icon /> : null}{children}</button>,
  InlineNotification: ({ title, subtitle }) => <div role="alert">{title}: {subtitle}</div>,
  Tile: (props) => <section {...props} />,
}));

vi.mock('@carbon/react/icons', () => ({ Calculator: () => null }));

import LoanCalculator from './LoanCalculator';

const localeCases = [
  ['en-US', 'Loan Calculator', 'Loan Amount ($)', 'Calculate'],
  ['en-GB', 'Loan Calculator', 'Loan Amount ($)', 'Calculate'],
  ['zh-TW', '貸款試算', '貸款金額（美元）', '計算'],
  ['zh-CN', '贷款试算', '贷款金额（美元）', '计算'],
];

describe('LoanCalculator localization', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
  });

  it.each(localeCases)('renders %s labels and the same calculation with locale formatting', async (locale, heading, amountLabel, calculateLabel) => {
    await i18n.changeLanguage(locale);
    render(<LoanCalculator />);

    expect(screen.getByRole('heading', { name: heading })).toBeVisible();
    expect(screen.getByLabelText(amountLabel)).toHaveValue(100000);
    fireEvent.click(screen.getByRole('button', { name: calculateLabel }));

    expect(screen.getByText(formatUsd(536.82, locale))).toBeVisible();
    expect(screen.getByText(formatUsd(100000, locale))).toBeVisible();
    expect(screen.getByText(formatUsd(93255.78, locale))).toBeVisible();
    expect(screen.getByText(formatUsd(193255.78, locale))).toBeVisible();
  });

  it('localizes validation without changing the positive-value rule', async () => {
    await i18n.changeLanguage('zh-TW');
    render(<LoanCalculator />);
    fireEvent.change(screen.getByLabelText('貸款金額（美元）'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: '計算' }));
    expect(screen.getByRole('alert')).toHaveTextContent('計算錯誤: 請在所有欄位輸入正數。');
  });
});
