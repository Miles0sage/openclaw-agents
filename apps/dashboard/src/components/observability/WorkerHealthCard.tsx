import { useMemo, useState } from 'react';
import type { HealthResponse } from '@/api/analytics';
import type { JobRecord } from '@/types/observability';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { CardShell, SkeletonBlock, timeAgoBadge } from './utils';

function dot(color: 'green' | 'amber' | 'red' | 'slate') {
  const cls =
    color === 'green'
      ? 'bg-green-500'
      : color === 'amber'
        ? 'bg-amber-500'
        : color === 'red'
          ? 'bg-red-500'
          : 'bg-slate-500';
  return <span className={`h-2.5 w-2.5 rounded-full ${cls}`} aria-hidden />;
}

function formatUptimeSec(sec: number | null | undefined): string {
  const s = typeof sec === 'number' && Number.isFinite(sec) ? sec : null;
  if (s == null) return '—';
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

export function WorkerHealthCard({
  health,
  dlq,
  loading,
  error,
  dlqError,
  lastUpdated,
}: {
  health: HealthResponse | null;
  dlq: JobRecord[];
  loading: boolean;
  error: string | null;
  dlqError: string | null;
  lastUpdated: number | null;
}) {
  const [showDlq, setShowDlq] = useState(false);

  const status = (health?.status ?? '').toString().toLowerCase();
  const isHealthy = status === 'healthy' || status === 'ok';

  const uptimeSec = health?.uptime_seconds ?? health?.uptime;

  const breakers = useMemo(() => {
    const b = (health as any)?.circuit_breakers ?? (health as any)?.breakers ?? null;
    if (!b || typeof b !== 'object') return [];
    return Object.entries(b as Record<string, any>).map(([k, v]) => ({
      name: k,
      state: String(v?.state ?? v ?? 'unknown'),
      detail: v?.detail ? String(v.detail) : v?.failures != null ? `${v.failures} failure(s)` : null,
    }));
  }, [health]);

  const workersActive =
    (health as any)?.active_workers ??
    (health as any)?.workers_active ??
    (health as any)?.workers?.active ??
    null;
  const workersTotal =
    (health as any)?.total_workers ??
    (health as any)?.workers_total ??
    (health as any)?.workers?.total ??
    null;

  return (
    <CardShell title="Worker health" right={timeAgoBadge(lastUpdated)}>
      {error && <ErrorBanner message={error} />}
      {loading && !health ? (
        <div className="space-y-3">
          <SkeletonBlock className="h-4 w-56" />
          <SkeletonBlock className="h-4 w-44" />
          <SkeletonBlock className="h-20 w-full" />
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {dot(isHealthy ? 'green' : 'red')}
              <span className="text-slate-200">Gateway:</span>
              <span className={isHealthy ? 'text-emerald-300' : 'text-rose-300'}>
                {health?.status ?? '—'}
              </span>
            </div>
            <span className="text-slate-500 text-xs">
              Uptime: {formatUptimeSec(uptimeSec)}
            </span>
          </div>

          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {dot(workersActive != null && workersTotal != null && workersActive === workersTotal ? 'green' : 'amber')}
              <span className="text-slate-200">Workers:</span>
              <span className="text-slate-400">
                {workersActive ?? '—'} active / {workersTotal ?? '—'} total
              </span>
            </div>
          </div>

          <div className="rounded border border-slate-700 bg-slate-800/30 p-3">
            <div className="text-slate-300 text-xs font-medium mb-2">Circuit breakers</div>
            {breakers.length === 0 ? (
              <p className="text-slate-500 text-xs">No circuit breaker data available.</p>
            ) : (
              <ul className="space-y-1">
                {breakers.map((b) => {
                  const s = b.state.toLowerCase();
                  const c = s.includes('open') ? 'red' : s.includes('half') ? 'amber' : s.includes('closed') ? 'green' : 'slate';
                  return (
                    <li key={b.name} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-slate-400">{b.name}</span>
                      <span className="flex items-center gap-2">
                        {dot(c as any)}
                        <span className="text-slate-200">{b.state}</span>
                        {b.detail && <span className="text-slate-500">{b.detail}</span>}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {dot(dlqError ? 'amber' : dlq.length > 0 ? 'red' : 'green')}
              <span className="text-slate-200">DLQ:</span>
              <span className="text-slate-400">{dlqError ? 'Unavailable' : `${dlq.length} unresolved job(s)`}</span>
            </div>
            <button
              type="button"
              onClick={() => setShowDlq((v) => !v)}
              className="text-xs text-sky-300 hover:text-sky-200 underline"
              disabled={dlq.length === 0}
              title={dlq.length === 0 ? 'No DLQ jobs' : 'View DLQ'}
            >
              View DLQ →
            </button>
          </div>

          {showDlq && dlq.length > 0 && (
            <div className="rounded border border-slate-700 bg-slate-800/30 p-3">
              <div className="text-slate-300 text-xs font-medium mb-2">Dead-letter queue</div>
              <ul className="space-y-1 text-xs">
                {dlq.slice(0, 6).map((j, i) => (
                  <li key={j.job_id ?? j.id ?? i} className="flex items-center justify-between gap-2">
                    <span className="font-mono text-slate-200">{j.job_id ?? j.id ?? '—'}</span>
                    <span className="text-slate-500 truncate">
                      {String(j.failure_type ?? j.error ?? j.status ?? '').slice(0, 60) || '—'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </CardShell>
  );
}

