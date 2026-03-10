import type {
  JobRecord,
  JobStats,
  ObservabilityCostPoint,
  ObservabilityErrorRatePoint,
  ObservabilityLatencyPoint,
} from '@/types/observability';

function isoHour(d: Date): string {
  const x = new Date(d);
  x.setMinutes(0, 0, 0);
  return x.toISOString();
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function mockJobStats(): JobStats {
  return { pending: 12, running: 3, failed: 2, dlq: 1 };
}

export function mockDlqJobs(): JobRecord[] {
  return [
    { job_id: 'job-1001', status: 'failed', failure_type: 'timeout', created_at: new Date(Date.now() - 86400_000).toISOString() },
    { job_id: 'job-1002', status: 'failed', failure_type: 'credit_exhausted', created_at: new Date(Date.now() - 2 * 86400_000).toISOString() },
  ];
}

export function mockDoneJobs(limit = 200): JobRecord[] {
  const out: JobRecord[] = [];
  for (let i = 0; i < limit; i++) {
    const hoursAgo = i % 24;
    const started = new Date(Date.now() - hoursAgo * 3600_000 - (i % 60) * 60_000);
    const durMin = 2 + ((i * 7) % 55);
    const completed = new Date(started.getTime() + durMin * 60_000);
    out.push({
      job_id: `job-${2000 + i}`,
      status: i % 9 === 0 ? 'failed' : 'done',
      created_at: started.toISOString(),
      started_at: started.toISOString(),
      completed_at: completed.toISOString(),
      cost_usd: Math.round((0.002 + ((i * 13) % 40) / 1000) * 1e6) / 1e6,
    });
  }
  return out;
}

export function mockLatencySeries(): ObservabilityLatencyPoint[] {
  const now = new Date();
  const pts: ObservabilityLatencyPoint[] = [];
  for (let i = 23; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3600_000);
    pts.push({
      hour: isoHour(d),
      p50_min: 6 + Math.sin(i / 3) * 1.2,
      p95_min: 18 + Math.cos(i / 4) * 2.5,
      sample_count: 8 + (i % 6),
    });
  }
  return pts;
}

export function mockErrorRateSeries(): ObservabilityErrorRatePoint[] {
  const now = new Date();
  const pts: ObservabilityErrorRatePoint[] = [];
  for (let i = 23; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3600_000);
    const total = 10 + (i % 7);
    const failed = i % 9 === 0 ? 4 : i % 5 === 0 ? 2 : 0;
    pts.push({
      hour: isoHour(d),
      total,
      failed,
      error_rate_pct: total ? (failed / total) * 100 : 0,
    });
  }
  return pts;
}

export function mockCostTrend(): ObservabilityCostPoint[] {
  const now = new Date();
  const pts: ObservabilityCostPoint[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 86400_000);
    const total = 0.25 + (6 - i) * 0.04 + Math.sin(i) * 0.02;
    const jobs = 40 + (i % 5) * 3;
    pts.push({
      day: isoDay(d),
      total_cost_usd: Math.round(total * 1e4) / 1e4,
      job_count: jobs,
      avg_cost_usd: Math.round((total / jobs) * 1e6) / 1e6,
    });
  }
  return pts;
}

