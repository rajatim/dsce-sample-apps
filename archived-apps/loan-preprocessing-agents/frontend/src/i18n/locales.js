export const SUPPORTED_LOCALES = Object.freeze(['zh-TW', 'zh-CN', 'en-US', 'en-GB']);
export const DEFAULT_LOCALE = 'en-US';
export const LOCALE_STORAGE_KEY = 'dsce.loan.locale';
export const NAMESPACES = Object.freeze([
  'common',
  'application',
  'applications',
  'logs',
  'calculator',
  'status',
]);

export const normalizeSupportedLocale = (candidate) => {
  if (typeof candidate !== 'string' || candidate.trim() === '') return null;

  try {
    const [canonicalLocale] = Intl.getCanonicalLocales(candidate.trim());
    return SUPPORTED_LOCALES.includes(canonicalLocale) ? canonicalLocale : null;
  } catch {
    return null;
  }
};

const normalizeBrowserLocale = (candidate) => {
  const supportedLocale = normalizeSupportedLocale(candidate);
  if (supportedLocale) return supportedLocale;
  if (typeof candidate !== 'string' || candidate.trim() === '') return null;

  try {
    const locale = new Intl.Locale(candidate.trim()).maximize();
    if (locale.language === 'zh') {
      return locale.script === 'Hant' || ['TW', 'HK', 'MO'].includes(locale.region)
        ? 'zh-TW'
        : 'zh-CN';
    }
    if (locale.language === 'en') return locale.region === 'GB' ? 'en-GB' : 'en-US';
  } catch {
    return null;
  }

  return null;
};

export const resolveInitialLocale = (preferences = {}) => {
  const { search = '', storedLocale = '', browserLocales = [] } = preferences ?? {};
  const queryLocale = new URLSearchParams(typeof search === 'string' ? search : '').get('lang');
  const supportedQueryLocale = normalizeSupportedLocale(queryLocale);
  if (supportedQueryLocale) return supportedQueryLocale;

  const supportedStoredLocale = normalizeSupportedLocale(storedLocale);
  if (supportedStoredLocale) return supportedStoredLocale;

  const browserCandidates = Array.isArray(browserLocales) ? browserLocales : [browserLocales];
  for (const candidate of browserCandidates) {
    const browserLocale = normalizeBrowserLocale(candidate);
    if (browserLocale) return browserLocale;
  }

  return DEFAULT_LOCALE;
};

export const setDocumentLocale = (locale) => {
  const supportedLocale = normalizeSupportedLocale(locale) ?? DEFAULT_LOCALE;
  if (typeof document !== 'undefined') document.documentElement.lang = supportedLocale;
  return supportedLocale;
};
