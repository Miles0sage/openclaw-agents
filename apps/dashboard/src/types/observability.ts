export type JobStatus =
  | 'pending'
  | 'running'
  | 'done'
  | 'failed'
  | 'error'
  | 'cancelled'
  | 'killed'
  | 'unknown';

export interface JobRecord {
  job_id?: string;
  id?: string;
  status?: JobStatus | string;
  agent_key?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  cost_usd?: number;
  error?: string;
  failure_type?: string;
  [key: string]: unknown;
}

export interface JobStats {
  pending: number;
  running: number;
  failed: number;
  dlq: number;
}

export interface ObservabilityCostPoint {
  day: string; // YYYY-MM-DD
  total_cost_usd: number;
  avg_cost_usd: number | null;
  job_count: number | null;
}

export interface ObservabilityLatencyPoint {
  hour: string; // ISO hour bucket label
  p50_min: number | null;
  p95_min: number | null;
  sample_count: number;
}

export interface ObservabilityErrorRatePoint {
  hour: string; // ISO hour bucket label
  error_rate_pct: number | null;
  total: number;
  failed: number;
}

