import { GATEWAY_BASE, USE_MOCKS, ANALYTICS_BASE } from './constants';
import type { JobRecord, JobStats } from '@/types/observability';

async function fetchGatewayApi<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${GATEWAY_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function fetchAnalyticsApi<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${ANALYTICS_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function getJobStats(): Promise<JobStats> {
  if (USE_MOCKS) return (await import('./mocks/observability')).mockJobStats();
  const data = await fetchGatewayApi<Record<string, unknown> | JobStats>('/api/jobs/stats');
  const obj = data as Record<string, unknown>;
  const pending = Number(obj.pending ?? (obj.counts as any)?.pending ?? 0);
  const running = Number(obj.running ?? (obj.counts as any)?.running ?? 0);
  const failed = Number(obj.failed ?? (obj.counts as any)?.failed ?? (obj.counts as any)?.error ?? 0);
  const dlq = Number(obj.dlq ?? (obj.counts as any)?.dlq ?? 0);
  return { pending, running, failed, dlq };
}

export async function getJobs(params: {
  status?: string;
  limit?: number;
  order?: string;
} = {}): Promise<JobRecord[]> {
  if (USE_MOCKS) return (await import('./mocks/observability')).mockDoneJobs(params.limit ?? 200);
  const q = new URLSearchParams();
  if (params.status) q.set('status', params.status);
  if (params.limit != null) q.set('limit', String(params.limit));
  if (params.order) q.set('order', params.order);
  const query = q.toString();
  const data = await fetchGatewayApi<JobRecord[] | { jobs?: JobRecord[] }>(`/api/jobs${query ? `?${query}` : ''}`);
  return Array.isArray(data) ? data : (data.jobs ?? []);
}

export async function getDlqJobs(): Promise<JobRecord[]> {
  if (USE_MOCKS) return (await import('./mocks/observability')).mockDlqJobs();
  const data = await fetchGatewayApi<JobRecord[] | { jobs?: JobRecord[] }>('/api/dlq');
  return Array.isArray(data) ? data : (data.jobs ?? []);
}

export async function getAnalyticsCosts(): Promise<{
  total_cost?: number;
  daily_costs?: Record<string, number>;
  timestamp?: string;
}> {
  // This is a fallback when /api/jobs isn't available; it gives daily totals.
  const data = await fetchAnalyticsApi<any>('/costs');
  return data ?? {};
}

