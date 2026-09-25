import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  normalizeSupportedLocale,
  setDocumentLocale,
} from '../../i18n/locales';
import './LanguageSwitcher.css';

const LanguageSwitcher = ({ id, className = '' }) => {
  const { i18n, t } = useTranslation('common');
  const location = useLocation();
  const navigate = useNavigate();
  const selectedLocale = normalizeSupportedLocale(i18n.language) ?? DEFAULT_LOCALE;

  const handleChange = (event) => {
    const locale = normalizeSupportedLocale(event.target.value) ?? DEFAULT_LOCALE;

    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      // Locale selection still works when browser storage is unavailable.
    }

    setDocumentLocale(locale);
    void i18n.changeLanguage(locale);

    const query = new URLSearchParams(location.search);
    query.set('lang', locale);
    navigate(
      {
        pathname: location.pathname,
        search: `?${query.toString()}`,
        hash: location.hash,
      },
      { replace: true },
    );
  };

  return (
    <div className={`loan-language-switcher ${className}`.trim()}>
      <label htmlFor={id}>{t('language.label')}</label>
      <select id={id} value={selectedLocale} onChange={handleChange}>
        {SUPPORTED_LOCALES.map((locale) => (
          <option key={locale} value={locale}>
            {t(`language.options.${locale}`)}
          </option>
        ))}
      </select>
    </div>
  );
};

export default LanguageSwitcher;
