import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getHealth, getTracesRecent } from '@/api/analytics';
import { getAnalyticsCosts, getDlqJobs, getJobs, getJobStats } from '@/api/observability';
import type { HealthResponse } from '@/api/analytics';
import type { TraceListItem } from '@/types/analytics';
import type {
  JobRecord,
  JobStats,
  ObservabilityCostPoint,
  ObservabilityErrorRatePoint,
  ObservabilityLatencyPoint,
} from '@/types/observability';
import { USE_MOCKS } from '@/api/constants';

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function percentile(sorted: number[], p: number): number | null {
  if (sorted.length === 0) return null;
  const idx = clamp(Math.round(p * (sorted.length - 1)), 0, sorted.length - 1);
  return sorted[idx] ?? null;
}

function isoHourBucket(d: Date): string {
  const x = new Date(d);
  x.setMinutes(0, 0, 0);
  return x.toISOString();
}

function isoDayBucket(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function hoursBackBuckets(hours: number): string[] {
  const now = new Date();
  const buckets: string[] = [];
  for (let i = hours - 1; i >= 0; i--) {
    buckets.push(isoHourBucket(new Date(now.getTime() - i * 3600_000)));
  }
  return buckets;
}

function daysBackBuckets(days: number): string[] {
  const now = new Date();
  const buckets: string[] = [];
  for (let i = days - 1; i >= 0; i--) {
    buckets.push(isoDayBucket(new Date(now.getTime() - i * 86400_000)));
  }
  return buckets;
}

function durationMinutes(job: JobRecord): number | null {
  const started = typeof job.started_at === 'string' ? new Date(job.started_at).getTime() : NaN;
  const completed = typeof job.completed_at === 'string' ? new Date(job.completed_at).getTime() : NaN;
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started) return null;
  return (completed - started) / 60000;
}

function jobHour(job: JobRecord): string | null {
  const t = typeof job.completed_at === 'string' ? new Date(job.completed_at) : typeof job.created_at === 'string' ? new Date(job.created_at) : null;
  if (!t || Number.isNaN(t.getTime())) return null;
  return isoHourBucket(t);
}

function jobDay(job: JobRecord): string | null {
  const t =
    typeof job.created_at === 'string'
      ? new Date(job.created_at)
      : typeof job.started_at === 'string'
        ? new Date(job.started_at)
        : typeof job.completed_at === 'string'
          ? new Date(job.completed_at)
          : null;
  if (!t || Number.isNaN(t.getTime())) return null;
  return isoDayBucket(t);
}

function isFailed(job: JobRecord): boolean {
  const s = String(job.status ?? '').toLowerCase();
  return s === 'failed' || s === 'error';
}

function isDone(job: JobRecord): boolean {
  const s = String(job.status ?? '').toLowerCase();
  return s === 'done' || s === 'completed' || s === 'ok' || s === 'success';
}

function toJobsFromTraces(traces: TraceListItem[]): JobRecord[] {
  return traces.map((t) => {
    const started = new Date(t.start_time);
    const completed = new Date(started.getTime() + (t.duration_ms ?? 0));
    const status = t.status === 'error' || t.status === 'failed' ? 'failed' : 'done';
    return {
      job_id: t.job_id,
      status,
      created_at: t.start_time,
      started_at: t.start_time,
      completed_at: completed.toISOString(),
    };
  });
}

function deriveLatencySeries(jobs: JobRecord[]): ObservabilityLatencyPoint[] {
  const buckets = hoursBackBuckets(24);
  const byHour = new Map<string, number[]>();
  for (const job of jobs) {
    const h = jobHour(job);
    if (!h) continue;
    const mins = durationMinutes(job);
    if (mins == null) continue;
    const arr = byHour.get(h) ?? [];
    arr.push(mins);
    byHour.set(h, arr);
  }
  return buckets.map((hour) => {
    const arr = [...(byHour.get(hour) ?? [])].sort((a, b) => a - b);
    return {
      hour,
      p50_min: percentile(arr, 0.5),
      p95_min: percentile(arr, 0.95),
      sample_count: arr.length,
    };
  });
}

function deriveErrorRateSeries(jobs: JobRecord[]): ObservabilityErrorRatePoint[] {
  const buckets = hoursBackBuckets(24);
  const totals = new Map<string, { total: number; failed: number }>();
  for (const job of jobs) {
    const h = jobHour(job);
    if (!h) continue;
    const t = totals.get(h) ?? { total: 0, failed: 0 };
    t.total += 1;
    if (isFailed(job)) t.failed += 1;
    totals.set(h, t);
  }
  return buckets.map((hour) => {
    const t = totals.get(hour) ?? { total: 0, failed: 0 };
    return {
      hour,
      total: t.total,
      failed: t.failed,
      error_rate_pct: t.total ? (t.failed / t.total) * 100 : null,
    };
  });
}

function deriveCostTrend(jobs: JobRecord[]): ObservabilityCostPoint[] {
  const buckets = daysBackBuckets(7);
  const byDay = new Map<string, { totalCost: number; count: number }>();
  for (const job of jobs) {
    const d = jobDay(job);
    if (!d) continue;
    const cost = typeof job.cost_usd === 'number' && Number.isFinite(job.cost_usd) ? job.cost_usd : null;
    if (cost == null) continue;
    const agg = byDay.get(d) ?? { totalCost: 0, count: 0 };
    agg.totalCost += cost;
    agg.count += 1;
    byDay.set(d, agg);
  }
  return buckets.map((day) => {
    const agg = byDay.get(day);
    if (!agg) return { day, total_cost_usd: 0, avg_cost_usd: null, job_count: null };
    return {
      day,
      total_cost_usd: agg.totalCost,
      job_count: agg.count,
      avg_cost_usd: agg.count ? agg.totalCost / agg.count : null,
    };
  });
}

export function useObservabilityData(): {
  queueStats: JobStats | null;
  jobs: JobRecord[];
  health: HealthResponse | null;
  dlq: JobRecord[];
  latencySeries: ObservabilityLatencyPoint[];
  errorRateSeries: ObservabilityErrorRatePoint[];
  costTrend: ObservabilityCostPoint[];
  isLoading: {
    queue: boolean;
    jobs: boolean;
    health: boolean;
    dlq: boolean;
  };
  errors: {
    queue: string | null;
    jobs: string | null;
    health: string | null;
    dlq: string | null;
    costs: string | null;
  };
  lastUpdated: {
    queue: number | null;
    jobs: number | null;
    health: number | null;
    dlq: number | null;
    costs: number | null;
  };
  refetch: () => void;
} {
  const [queueStats, setQueueStats] = useState<JobStats | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [dlq, setDlq] = useState<JobRecord[]>([]);

  const [loading, setLoading] = useState({
    queue: true,
    jobs: true,
    health: true,
    dlq: true,
  });
  const [errors, setErrors] = useState({
    queue: null as string | null,
    jobs: null as string | null,
    health: null as string | null,
    dlq: null as string | null,
    costs: null as string | null,
  });
  const [lastUpdated, setLastUpdated] = useState({
    queue: null as number | null,
    jobs: null as number | null,
    health: null as number | null,
    dlq: null as number | null,
    costs: null as number | null,
  });

  const costFallbackRef = useRef<ObservabilityCostPoint[] | null>(null);

  const refetch = useCallback(() => {
    setLoading((p) => ({ ...p, queue: true, jobs: true, health: true, dlq: true }));
    setErrors((p) => ({ ...p, queue: null, jobs: null, health: null, dlq: null, costs: null }));

    const ops = [
      getJobStats(),
      (async () => {
        try {
          // Preferred per spec
          return await getJobs({ status: 'done', limit: 500 });
        } catch {
          // Fallback to traces/recent if /api/jobs isn't live yet
          const recent = await getTracesRecent(200);
          return toJobsFromTraces(recent.traces ?? []);
        }
      })(),
      getHealth(),
      getDlqJobs(),
    ] as const;

    Promise.allSettled(ops).then(async ([qs, jobsRes, healthRes, dlqRes]) => {
      const now = Date.now();

      if (qs.status === 'fulfilled') {
        setQueueStats(qs.value);
        setLastUpdated((p) => ({ ...p, queue: now }));
      } else {
        setErrors((p) => ({ ...p, queue: qs.reason instanceof Error ? qs.reason.message : 'Failed to load queue stats' }));
      }
      setLoading((p) => ({ ...p, queue: false }));

      if (jobsRes.status === 'fulfilled') {
        setJobs(jobsRes.value);
        setLastUpdated((p) => ({ ...p, jobs: now }));
      } else {
        setErrors((p) => ({ ...p, jobs: jobsRes.reason instanceof Error ? jobsRes.reason.message : 'Failed to load jobs' }));
      }
      setLoading((p) => ({ ...p, jobs: false }));

      if (healthRes.status === 'fulfilled') {
        setHealth(healthRes.value);
        setLastUpdated((p) => ({ ...p, health: now }));
      } else {
        setErrors((p) => ({ ...p, health: healthRes.reason instanceof Error ? healthRes.reason.message : 'Failed to load health' }));
      }
      setLoading((p) => ({ ...p, health: false }));

      if (dlqRes.status === 'fulfilled') {
        setDlq(dlqRes.value);
        setLastUpdated((p) => ({ ...p, dlq: now }));
      } else {
        setErrors((p) => ({ ...p, dlq: dlqRes.reason instanceof Error ? dlqRes.reason.message : 'Failed to load DLQ' }));
      }
      setLoading((p) => ({ ...p, dlq: false }));

      // Cost trend: prefer job list with cost_usd; fallback to analytics /costs daily totals.
      try {
        let trend: ObservabilityCostPoint[] | null = null;
        if (jobsRes.status === 'fulfilled') {
          const derived = deriveCostTrend(jobsRes.value);
          const hasAnyCost = derived.some((d) => (d.total_cost_usd ?? 0) > 0);
          trend = hasAnyCost ? derived : null;
        }

        if (!trend) {
          if (USE_MOCKS) {
            trend = (await import('@/api/mocks/observability')).mockCostTrend();
          } else {
            const costs = await getAnalyticsCosts();
            const buckets = daysBackBuckets(7);
            trend = buckets.map((day) => ({
              day,
              total_cost_usd: Number(costs.daily_costs?.[day] ?? 0),
              avg_cost_usd: null,
              job_count: null,
            }));
          }
        }
        costFallbackRef.current = trend;
        setLastUpdated((p) => ({ ...p, costs: now }));
      } catch (e) {
        setErrors((p) => ({ ...p, costs: e instanceof Error ? e.message : 'Failed to load costs' }));
      }
    });
  }, []);

  useEffect(() => {
    refetch();
    const id = setInterval(refetch, 30_000);
    return () => clearInterval(id);
  }, [refetch]);

  const latencySeries = useMemo(() => deriveLatencySeries(jobs.filter((j) => isDone(j) || isFailed(j))), [jobs]);
  const errorRateSeries = useMemo(() => deriveErrorRateSeries(jobs.filter((j) => isDone(j) || isFailed(j))), [jobs]);
  const costTrend = useMemo(() => costFallbackRef.current ?? deriveCostTrend(jobs), [jobs]);

  return {
    queueStats,
    jobs,
    health,
    dlq,
    latencySeries,
    errorRateSeries,
    costTrend,
    isLoading: loading,
    errors,
    lastUpdated,
    refetch,
  };
}

