import { DEFAULT_LOCALE, normalizeSupportedLocale } from './locales';

const safeLocale = (locale) => normalizeSupportedLocale(locale) ?? DEFAULT_LOCALE;

export const formatDateTime = (value, locale) =>
  new Intl.DateTimeFormat(safeLocale(locale), {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));

export const formatNumber = (value, locale) =>
  new Intl.NumberFormat(safeLocale(locale)).format(value);

export const formatUsd = (value, locale) =>
  new Intl.NumberFormat(safeLocale(locale), {
    style: 'currency',
    currency: 'USD',
  }).format(value);
