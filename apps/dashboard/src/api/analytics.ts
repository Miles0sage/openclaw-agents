import {
  type JudgeSummary,
  type TraceDetail,
  type TracesResponse,
  type KgSummary,
  type KgRecommendResponse,
  type AgentsResponse,
} from '@/types/analytics';
import { ANALYTICS_BASE, GATEWAY_BASE, USE_MOCKS } from './constants';

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${ANALYTICS_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function getJudgeSummary(days: number): Promise<JudgeSummary> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockJudgeSummary(days);
  return fetchApi<JudgeSummary>(`/judge/summary?days=${days}`);
}

export async function getJudge(jobId: string): Promise<{ score: number; dimensions?: Record<string, number> }> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockJudge(jobId);
  return fetchApi(`/judge/${encodeURIComponent(jobId)}`);
}

export async function getTraces(limit: number): Promise<TracesResponse> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockTraces(limit);
  return fetchApi<TracesResponse>(`/traces?limit=${limit}`);
}

export async function getTracesRecent(limit: number): Promise<TracesResponse> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockTracesRecent(limit);
  const url = `${ANALYTICS_BASE}/traces/recent?limit=${limit}`;
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' } });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<TracesResponse>;
}

export async function getTrace(jobId: string): Promise<TraceDetail> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockTrace(jobId);
  return fetchApi<TraceDetail>(`/traces/${encodeURIComponent(jobId)}`);
}

export async function getKgSummary(): Promise<KgSummary> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockKgSummary();
  return fetchApi<KgSummary>('/kg/summary');
}

export async function getKgRecommend(agentKey: string): Promise<KgRecommendResponse> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockKgRecommend(agentKey);
  return fetchApi<KgRecommendResponse>(`/kg/tools/recommend?agent_key=${encodeURIComponent(agentKey)}`);
}

export async function getDag(workflowId: string): Promise<unknown> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockDag(workflowId);
  return fetchApi(`/dag/${encodeURIComponent(workflowId)}`);
}

export async function getAgents(): Promise<AgentsResponse> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockAgents();
  return fetchApi<AgentsResponse>('/agents');
}

export function getStreamUrl(jobId: string): string {
  return `${ANALYTICS_BASE}/stream/${encodeURIComponent(jobId)}`;
}

export interface HealthResponse {
  status?: string;
  uptime?: number;
  uptime_seconds?: number;
  total_tools?: number;
  tools_count?: number;
  python_version?: string;
  version?: string;
  memory_usage?: number;
  memory_mb?: number;
  timestamp?: string;
}

export async function getHealth(): Promise<HealthResponse> {
  if (USE_MOCKS) return (await import('./mocks/analytics')).mockHealth();
  const res = await fetch(`${GATEWAY_BASE}/health`, { headers: { 'Content-Type': 'application/json' } });
  if (!res.ok) throw new Error(`Health ${res.status}: ${res.statusText}`);
  return res.json() as Promise<HealthResponse>;
}
