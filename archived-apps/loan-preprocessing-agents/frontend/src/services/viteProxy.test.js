// @vitest-environment node
import { describe, expect, it } from 'vitest';
import viteConfig from '../../vite.config';

describe('Vite API proxy', () => {
  it('forwards local /api calls to FastAPI without the /api prefix', () => {
    const proxy = viteConfig.server?.proxy?.['/api'];

    expect(proxy?.target).toBe('http://127.0.0.1:8000');
    expect(proxy?.rewrite('/api/applications/app_123')).toBe('/applications/app_123');
  });
});
