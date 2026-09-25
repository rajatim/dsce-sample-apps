import { createInstance } from 'i18next';
import { initReactI18next } from 'react-i18next';
import enGBApplication from './locales/en-GB/application.json';
import enGBApplications from './locales/en-GB/applications.json';
import enGBCalculator from './locales/en-GB/calculator.json';
import enGBCommon from './locales/en-GB/common.json';
import enGBLogs from './locales/en-GB/logs.json';
import enGBStatus from './locales/en-GB/status.json';
import enUSApplication from './locales/en-US/application.json';
import enUSApplications from './locales/en-US/applications.json';
import enUSCalculator from './locales/en-US/calculator.json';
import enUSCommon from './locales/en-US/common.json';
import enUSLogs from './locales/en-US/logs.json';
import enUSStatus from './locales/en-US/status.json';
import zhCNApplication from './locales/zh-CN/application.json';
import zhCNApplications from './locales/zh-CN/applications.json';
import zhCNCalculator from './locales/zh-CN/calculator.json';
import zhCNCommon from './locales/zh-CN/common.json';
import zhCNLogs from './locales/zh-CN/logs.json';
import zhCNStatus from './locales/zh-CN/status.json';
import zhTWApplication from './locales/zh-TW/application.json';
import zhTWApplications from './locales/zh-TW/applications.json';
import zhTWCalculator from './locales/zh-TW/calculator.json';
import zhTWCommon from './locales/zh-TW/common.json';
import zhTWLogs from './locales/zh-TW/logs.json';
import zhTWStatus from './locales/zh-TW/status.json';
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  NAMESPACES,
  SUPPORTED_LOCALES,
  resolveInitialLocale,
  setDocumentLocale,
} from './locales';

export const resources = {
  'en-US': {
    common: enUSCommon,
    application: enUSApplication,
    applications: enUSApplications,
    logs: enUSLogs,
    calculator: enUSCalculator,
    status: enUSStatus,
  },
  'en-GB': {
    common: enGBCommon,
    application: enGBApplication,
    applications: enGBApplications,
    logs: enGBLogs,
    calculator: enGBCalculator,
    status: enGBStatus,
  },
  'zh-TW': {
    common: zhTWCommon,
    application: zhTWApplication,
    applications: zhTWApplications,
    logs: zhTWLogs,
    calculator: zhTWCalculator,
    status: zhTWStatus,
  },
  'zh-CN': {
    common: zhCNCommon,
    application: zhCNApplication,
    applications: zhCNApplications,
    logs: zhCNLogs,
    calculator: zhCNCalculator,
    status: zhCNStatus,
  },
};

const readStoredLocale = () => {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
};

const readBrowserLocales = () => {
  if (typeof navigator === 'undefined') return [];
  if (Array.isArray(navigator.languages) && navigator.languages.length > 0) {
    return navigator.languages;
  }
  return navigator.language ? [navigator.language] : [];
};

export const initialLocale = resolveInitialLocale({
  search: typeof window === 'undefined' ? '' : window.location.search,
  storedLocale: readStoredLocale(),
  browserLocales: readBrowserLocales(),
});

setDocumentLocale(initialLocale);

const i18n = createInstance();
i18n.use(initReactI18next).init({
  resources,
  lng: initialLocale,
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: SUPPORTED_LOCALES,
  ns: NAMESPACES,
  defaultNS: 'common',
  load: 'currentOnly',
  initAsync: false,
  interpolation: {
    escapeValue: false,
  },
  react: {
    useSuspense: false,
  },
});

export default i18n;
