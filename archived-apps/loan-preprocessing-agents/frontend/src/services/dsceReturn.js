export const DSCE_RETURN_STORAGE_KEY = 'loan-demo-dsce-return';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

const isLoopback = (hostname) => LOOPBACK_HOSTS.has(hostname);

const getExpectedDsceHost = (location) => {
  if (isLoopback(location.hostname)) return null;
  if (!location.hostname.startsWith('loan-demo-')) return null;
  return location.hostname.replace(/^loan-demo-/, '');
};

export const isTrustedDsceReturnUrl = (value, location = window.location) => {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return false;
    if (url.pathname !== '/dsce' && !url.pathname.startsWith('/dsce/')) return false;

    if (isLoopback(location.hostname)) {
      return isLoopback(url.hostname);
    }

    return url.protocol === 'https:' && url.hostname === getExpectedDsceHost(location);
  } catch {
    return false;
  }
};

const getDsceFallbackUrl = (location, locale) => {
  const localeSegment = locale && locale !== 'en-US' ? `${locale}/` : '';

  if (isLoopback(location.hostname)) {
    return `http://localhost:3000/dsce/${localeSegment}watsonx`;
  }

  const expectedHost = getExpectedDsceHost(location);
  if (!expectedHost) return null;
  return `https://${expectedHost}/dsce/${localeSegment}watsonx`;
};

export const resolveDsceReturnUrl = ({
  search,
  location = window.location,
  storage = window.sessionStorage,
  locale = 'en-US',
}) => {
  const requestedUrl = new URLSearchParams(search).get('returnTo');
  if (requestedUrl && isTrustedDsceReturnUrl(requestedUrl, location)) {
    storage.setItem(DSCE_RETURN_STORAGE_KEY, requestedUrl);
    return requestedUrl;
  }

  const storedUrl = storage.getItem(DSCE_RETURN_STORAGE_KEY);
  if (storedUrl && isTrustedDsceReturnUrl(storedUrl, location)) return storedUrl;

  return getDsceFallbackUrl(location, locale);
};
