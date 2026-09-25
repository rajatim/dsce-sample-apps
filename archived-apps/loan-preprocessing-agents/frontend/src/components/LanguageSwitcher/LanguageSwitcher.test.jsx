import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../../i18n/config';
import { LOCALE_STORAGE_KEY } from '../../i18n/locales';
import LanguageSwitcher from './LanguageSwitcher';

const CurrentLocation = () => {
  const location = useLocation();
  return <output aria-label="Current URL">{`${location.pathname}${location.search}${location.hash}`}</output>;
};

describe('LanguageSwitcher', () => {
  beforeEach(async () => {
    const storage = new Map();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: (key) => storage.delete(key),
        clear: () => storage.clear(),
      },
    });
    window.history.replaceState({}, '', '/');
    await i18n.changeLanguage('en-US');
    document.documentElement.lang = 'en-US';
    vi.stubGlobal('fetch', vi.fn());
  });

  it('changes only lang while persisting the locale and making no network call', async () => {
    render(
      <MemoryRouter initialEntries={['/apply?demo=1&lang=en-US#form']}>
        <LanguageSwitcher id="test-language" />
        <CurrentLocation />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByRole('combobox', { name: 'Language' }), {
      target: { value: 'zh-TW' },
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: '語言' })).toHaveValue('zh-TW');
    });
    expect(screen.getByLabelText('Current URL')).toHaveTextContent(
      '/apply?demo=1&lang=zh-TW#form',
    );
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-TW');
    expect(document.documentElement).toHaveAttribute('lang', 'zh-TW');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renders the exact fixed locale choices', () => {
    render(
      <MemoryRouter initialEntries={['/apply?lang=en-US']}>
        <LanguageSwitcher id="test-language" />
      </MemoryRouter>,
    );

    expect(screen.getAllByRole('option').map((option) => option.value)).toEqual([
      'zh-TW',
      'zh-CN',
      'en-US',
      'en-GB',
    ]);
  });
});
