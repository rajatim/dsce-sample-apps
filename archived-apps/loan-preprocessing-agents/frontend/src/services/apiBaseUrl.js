export const buildApiUrl = (path) => {
  const baseUrl = (import.meta.env.VITE_API_URL?.trim() || '/api').replace(/\/+$/, '');
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
};
