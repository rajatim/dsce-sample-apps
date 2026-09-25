import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  resolveInitialLocale,
  setDocumentLocale,
} from './locales';

describe('resolveInitialLocale', () => {
  it('exposes only the four supported locales and the en-US default', () => {
    expect(SUPPORTED_LOCALES).toEqual(['zh-TW', 'zh-CN', 'en-US', 'en-GB']);
    expect(DEFAULT_LOCALE).toBe('en-US');
    expect(LOCALE_STORAGE_KEY).toBe('dsce.loan.locale');
  });

  it('uses a valid query locale before stored and browser preferences', () => {
    expect(
      resolveInitialLocale({
        search: '?lang=zh-CN',
        storedLocale: 'en-GB',
        browserLocales: ['en-US'],
      }),
    ).toBe('zh-CN');
  });

  it('uses a valid stored locale when the query is absent or invalid', () => {
    expect(
      resolveInitialLocale({
        search: '',
        storedLocale: 'en-GB',
        browserLocales: ['zh-TW'],
      }),
    ).toBe('en-GB');
    expect(
      resolveInitialLocale({
        search: '?lang=../../secret',
        storedLocale: 'zh-TW',
        browserLocales: ['zh-CN'],
      }),
    ).toBe('zh-TW');
    expect(
      resolveInitialLocale({
        search: '?lang=zh-Hans-CN',
        storedLocale: 'en-GB',
        browserLocales: ['zh-TW'],
      }),
    ).toBe('en-GB');
  });

  it('uses the first browser locale that can be normalized', () => {
    expect(
      resolveInitialLocale({
        search: '',
        storedLocale: '',
        browserLocales: ['fr-FR', 'zh-Hans-CN', 'en-GB'],
      }),
    ).toBe('zh-CN');
    expect(
      resolveInitialLocale({
        search: '',
        storedLocale: 'not-supported',
        browserLocales: ['fr-FR', 'zh-Hant-HK'],
      }),
    ).toBe('zh-TW');
  });

  it('falls back to en-US after all candidates are exhausted', () => {
    expect(
      resolveInitialLocale({
        search: '?lang=../../secret',
        storedLocale: 'constructor',
        browserLocales: ['__proto__', 'fr-FR'],
      }),
    ).toBe('en-US');
    expect(resolveInitialLocale()).toBe('en-US');
  });
});

describe('setDocumentLocale', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('lang');
  });

  it('sets only an allowlisted locale on the document', () => {
    expect(setDocumentLocale('zh-TW')).toBe('zh-TW');
    expect(document.documentElement).toHaveAttribute('lang', 'zh-TW');

    expect(setDocumentLocale('../../secret')).toBe('en-US');
    expect(document.documentElement).toHaveAttribute('lang', 'en-US');
  });
});

describe('i18n configuration', () => {
  beforeEach(() => {
    const storage = new Map();
    vi.stubGlobal('localStorage', {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    });
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
    document.documentElement.removeAttribute('lang');
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('initializes all resources with the resolved locale before consumers render', async () => {
    window.history.replaceState({}, '', '/?lang=zh-CN');
    localStorage.setItem(LOCALE_STORAGE_KEY, 'en-GB');
    vi.resetModules();

    const { default: i18n, initialLocale } = await import('./config');

    expect(initialLocale).toBe('zh-CN');
    expect(i18n.isInitialized).toBe(true);
    expect(i18n.language).toBe('zh-CN');
    expect(i18n.languages[0]).toBe('zh-CN');
    expect(document.documentElement).toHaveAttribute('lang', 'zh-CN');
    expect([].concat(i18n.options.fallbackLng)).toContain('en-US');
    expect(i18n.options.load).toBe('currentOnly');
    expect(i18n.options.interpolation.escapeValue).toBe(false);
    expect(i18n.options.react.useSuspense).toBe(false);

    SUPPORTED_LOCALES.forEach((locale) => {
      ['common', 'application', 'applications', 'logs', 'calculator', 'status'].forEach(
        (namespace) => {
          expect(i18n.hasResourceBundle(locale, namespace)).toBe(true);
        },
      );
    });
  });
});

describe('resource parity validation', () => {
  it('reports recursive missing, extra, blank, and leaf-type mismatches', async () => {
    const { validateLocaleTree } = await import('../../scripts/check-i18n.mjs');
    const reference = {
      section: { present: 'Reference', missing: 'Required' },
      typed: 'Text',
      blank: 'Not blank',
    };
    const candidate = {
      section: { present: '翻譯' },
      typed: 42,
      blank: '  ',
      extra: 'Unexpected',
    };

    expect(validateLocaleTree(reference, candidate)).toEqual([
      'missing:section.missing',
      'extra:extra',
      'blank:blank',
      'type:typed:string!=number',
    ]);
  });
});
