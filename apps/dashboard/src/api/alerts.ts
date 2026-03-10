import type { Alert, RunbookEntry } from '@/types/alerts';
import { GATEWAY_BASE, USE_MOCKS } from './constants';

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${GATEWAY_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export interface AlertsParams {
  limit?: number;
  severity?: string;
  job_id?: string;
}

export async function getAlerts(params: AlertsParams = {}): Promise<Alert[]> {
  if (USE_MOCKS) return (await import('./mocks/alerts')).mockGetAlerts(params);
  const q = new URLSearchParams();
  if (params.limit != null) q.set('limit', String(params.limit));
  if (params.severity) q.set('severity', params.severity);
  if (params.job_id) q.set('job_id', params.job_id);
  const query = q.toString();
  const data = await fetchApi<Alert[] | { alerts?: Alert[] }>(`/api/alerts${query ? `?${query}` : ''}`);
  return Array.isArray(data) ? data : (data?.alerts ?? []);
}

export async function acknowledgeAlert(alertId: string): Promise<void> {
  if (USE_MOCKS) return (await import('./mocks/alerts')).mockAcknowledgeAlert(alertId);
  await fetchApi(`/api/alerts/${encodeURIComponent(alertId)}/acknowledge`, { method: 'POST' });
}

export async function getRunbook(): Promise<RunbookEntry[]> {
  if (USE_MOCKS) return (await import('./mocks/alerts')).mockGetRunbook();
  const data = await fetchApi<{ runbook?: RunbookEntry[] }>('/api/runbook');
  return Array.isArray(data) ? data : (data.runbook ?? []);
}

export async function getRunbookEntry(failureType: string): Promise<RunbookEntry | null> {
  if (USE_MOCKS) return (await import('./mocks/alerts')).mockGetRunbookEntry(failureType);
  try {
    return await fetchApi<RunbookEntry>(`/api/runbook/${encodeURIComponent(failureType)}`);
  } catch {
    return null;
  }
}
