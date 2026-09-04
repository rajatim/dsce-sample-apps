import { buildApiUrl } from './apiBaseUrl';

const DEMO_USERNAME = 'tom_miller';
const DEMO_PASSWORD = 'Pass1234';

let tokenRequest = null;

export const requestDemoToken = () => {
  if (tokenRequest) {
    return tokenRequest;
  }

  const formData = new URLSearchParams();
  formData.append('username', DEMO_USERNAME);
  formData.append('password', DEMO_PASSWORD);

  tokenRequest = fetch(buildApiUrl('/token'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData,
  })
    .then(async (response) => {
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'The demo service could not be reached.');
      }

      const data = await response.json();
      if (!data.access_token) {
        throw new Error('The demo service did not return an access token.');
      }
      return data.access_token;
    })
    .finally(() => {
      tokenRequest = null;
    });

  return tokenRequest;
};
