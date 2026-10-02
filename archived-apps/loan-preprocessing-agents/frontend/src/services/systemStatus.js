import { authFetch } from './api';
import { buildApiUrl } from './apiBaseUrl';

const SAFE_ERROR = 'Demo status is currently unavailable.';
const STATUS_VALUES = new Set(['ready', 'limited', 'unavailable', 'checking', 'unknown', 'not_configured']);
const EVIDENCE_VALUES = new Set(['live_check', 'configured', 'recent_execution', 'not_verified']);

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isOptionalDate = (value) => value === null || (typeof value === 'string' && !Number.isNaN(Date.parse(value)));

const optionalText = (v, max) => v == null || (typeof v === 'string' && v.length <= max);
const validProblem = (p) => p == null || (isRecord(p)
  && ['provider', 'response', 'configuration', 'registration', 'timeout', 'connection', 'unknown', 'quota', 'authorization'].includes(p.category)
  && typeof p.service === 'string' && typeof p.stage === 'string' && typeof p.code === 'string'
  && typeof p.retryable_now === 'boolean' && typeof p.action === 'string'
  && (p.http_status == null || (Number.isInteger(p.http_status) && p.http_status >= 100 && p.http_status <= 599))
  && optionalText(p.provider_code, 128) && optionalText(p.provider_message, 512)
  && optionalText(p.trace_id, 128) && optionalText(p.blocked_by, 128));
const validFreshness = (v) => (v.stale === undefined || typeof v.stale === 'boolean')
  && (v.age_seconds === undefined || (Number.isFinite(v.age_seconds) && v.age_seconds >= 0));

const validDependency = (value) => isRecord(value)
  && typeof value.id === 'string'
  && typeof value.label === 'string'
  && STATUS_VALUES.has(value.status)
  && EVIDENCE_VALUES.has(value.evidence)
  && typeof value.message === 'string'
  && isOptionalDate(value.checked_at ?? null)
  && isOptionalDate(value.last_success_at ?? null)
  && isOptionalDate(value.last_failure_at ?? null) && validFreshness(value) && validProblem(value.problem);

const validCapability = (value) => isRecord(value)
  && typeof value.id === 'string'
  && typeof value.label === 'string'
  && STATUS_VALUES.has(value.status)
  && typeof value.message === 'string' && validFreshness(value);

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
  && value.dependencies.every(validDependency)
  && (value.revision === undefined || (Number.isSafeInteger(value.revision) && value.revision >= 0))
  && (value.instance_id === undefined || typeof value.instance_id === 'string')
  && (value.refresh == null || (isRecord(value.refresh)
    && ['executed', 'shared', 'cooldown'].includes(value.refresh.result)
    && Array.isArray(value.refresh.affected_ids)
    && value.refresh.affected_ids.every((id) => typeof id === 'string')
    && Number.isInteger(value.refresh.retry_after_seconds) && value.refresh.retry_after_seconds >= 0));

export const fetchSystemStatus = async ({ refresh = false, dependency, signal } = {}) => {
  try {
    const query = refresh ? `?refresh=true${dependency ? `&dependency=${encodeURIComponent(dependency)}` : ''}` : '';
    const response = await authFetch(buildApiUrl(`/system-status${query}`), { signal });
    if (!response?.ok) throw new Error(SAFE_ERROR);
    const payload = await response.json();
    if (!validPayload(payload)) throw new Error(SAFE_ERROR);
    return payload;
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new Error(SAFE_ERROR);
  }
};

export { SAFE_ERROR };
