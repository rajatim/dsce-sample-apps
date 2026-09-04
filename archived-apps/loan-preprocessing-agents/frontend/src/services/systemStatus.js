import { authFetch } from './api';
import { buildApiUrl } from './apiBaseUrl';

const SAFE_ERROR = 'Demo status is currently unavailable.';
const STATUS_VALUES = new Set(['ready', 'limited', 'unavailable', 'checking', 'unknown', 'not_configured']);
const EVIDENCE_VALUES = new Set(['live_check', 'configured', 'recent_execution', 'not_verified']);

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isOptionalDate = (value) => value === null || (typeof value === 'string' && !Number.isNaN(Date.parse(value)));

const validDependency = (value) => isRecord(value)
  && typeof value.id === 'string'
  && typeof value.label === 'string'
  && STATUS_VALUES.has(value.status)
  && EVIDENCE_VALUES.has(value.evidence)
  && typeof value.message === 'string'
  && isOptionalDate(value.checked_at ?? null)
  && isOptionalDate(value.last_success_at ?? null)
  && isOptionalDate(value.last_failure_at ?? null);

const validCapability = (value) => isRecord(value)
  && typeof value.id === 'string'
  && typeof value.label === 'string'
  && STATUS_VALUES.has(value.status)
  && typeof value.message === 'string';

const validPayload = (value) => isRecord(value)
  && isRecord(value.overall)
  && STATUS_VALUES.has(value.overall.status)
  && typeof value.overall.title === 'string'
  && typeof value.overall.message === 'string'
  && typeof value.checked_at === 'string'
  && !Number.isNaN(Date.parse(value.checked_at))
  && Number.isInteger(value.stale_after_seconds)
  && typeof value.stale === 'boolean'
  && Array.isArray(value.capabilities)
  && value.capabilities.every(validCapability)
  && Array.isArray(value.dependencies)
  && value.dependencies.every(validDependency);

export const fetchSystemStatus = async ({ refresh = false, signal } = {}) => {
  try {
    const query = refresh ? '?refresh=true' : '';
    const response = await authFetch(buildApiUrl(`/system-status${query}`), { signal });
    if (!response?.ok) throw new Error(SAFE_ERROR);
    const payload = await response.json();
    if (!validPayload(payload)) throw new Error(SAFE_ERROR);
    return payload;
  } catch {
    throw new Error(SAFE_ERROR);
  }
};

export { SAFE_ERROR };
