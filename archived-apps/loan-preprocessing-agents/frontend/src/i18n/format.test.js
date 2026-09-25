import { describe, expect, it } from 'vitest';
import { formatDateTime, formatNumber, formatUsd } from './format';

const FIXED_TIMESTAMP = Date.parse('2025-01-15T12:34:56.000Z');
const LOCALES = ['zh-TW', 'zh-CN', 'en-US', 'en-GB'];

describe('formatDateTime', () => {
  it('uses each locale date and time structure for a fixed UTC timestamp', () => {
    expect(formatDateTime(FIXED_TIMESTAMP, 'en-US')).toMatch(
      /^Jan \d{1,2}, 2025, \d{1,2}:\d{2} (AM|PM)$/,
    );
    expect(formatDateTime(FIXED_TIMESTAMP, 'en-GB')).toMatch(
      /^\d{1,2} Jan 2025, \d{2}:\d{2}$/,
    );
    expect(formatDateTime(FIXED_TIMESTAMP, 'zh-TW')).toMatch(
      /^2025年1月\d{1,2}日 \D*\d{1,2}:\d{2}$/,
    );
    expect(formatDateTime(FIXED_TIMESTAMP, 'zh-CN')).toMatch(
      /^2025年1月\d{1,2}日 \d{2}:\d{2}$/,
    );
  });
});

describe('numeric formatting', () => {
  it('formats USD explicitly in all four locales', () => {
    expect(Object.fromEntries(LOCALES.map((locale) => [locale, formatUsd(1234.5, locale)]))).toEqual({
      'zh-TW': 'US$1,234.50',
      'zh-CN': 'US$1,234.50',
      'en-US': '$1,234.50',
      'en-GB': 'US$1,234.50',
    });
  });

  it('formats ordinary numbers without changing the input values', () => {
    const amount = 1234567.89;
    const timestamp = FIXED_TIMESTAMP;

    expect(formatNumber(amount, 'en-US')).toBe('1,234,567.89');
    LOCALES.forEach((locale) => {
      formatNumber(amount, locale);
      formatUsd(amount, locale);
      formatDateTime(timestamp, locale);
    });

    expect(amount).toBe(1234567.89);
    expect(timestamp).toBe(FIXED_TIMESTAMP);
  });

  it('falls back to en-US rather than passing an unsafe locale to Intl', () => {
    expect(formatUsd(1234.5, '../../secret')).toBe('$1,234.50');
    expect(formatNumber(1234.5, 'constructor')).toBe('1,234.5');
  });
});
