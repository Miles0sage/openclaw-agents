import { useEffect, useState, useCallback } from 'react';
import { getHealth, type HealthResponse } from '@/api/analytics';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';

export function SystemHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchHealth = useCallback(() => {
    getHealth()
      .then((data) => {
        setHealth(data);
        setError(null);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Health check failed');
        setHealth(null);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 10_000);
    return () => clearInterval(id);
  }, [fetchHealth]);

  const isHealthy = health && (health.status === 'healthy' || health.status === 'ok');
  const uptimeSec = health?.uptime_seconds ?? health?.uptime ?? 0;
  const toolsCount = health?.total_tools ?? health?.tools_count ?? 0;
  const memoryPct = health?.memory_usage ?? (health?.memory_mb != null ? health.memory_mb / 1024 : undefined);

  if (loading && !health && !error) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-4">
        <h3 className="text-sm font-medium text-slate-300">System health</h3>
        <LoadingSpinner label="Loading health…" />
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-4 card-hover animate-slide-up">
      <h3 className="text-sm font-medium text-slate-300">System health</h3>
      {error && <ErrorBanner message={error} onRetry={fetchHealth} />}
      {health && (
        <>
          <div className="flex items-center gap-2">
            <span
              className="h-3 w-3 rounded-full shrink-0"
              style={{ backgroundColor: isHealthy ? '#22c55e' : '#ef4444' }}
              title={health.status ?? (isHealthy ? 'healthy' : 'unhealthy')}
              aria-hidden
            />
            <span className="text-slate-200 text-sm">
              {health.status ?? (isHealthy ? 'Healthy' : 'Unhealthy')}
            </span>
          </div>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-slate-500">Uptime</dt>
              <dd className="text-slate-200 font-mono">
                {uptimeSec >= 3600
                  ? `${(uptimeSec / 3600).toFixed(1)}h`
                  : uptimeSec >= 60
                    ? `${Math.round(uptimeSec / 60)}m`
                    : `${uptimeSec}s`}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">Total tools</dt>
              <dd className="text-slate-200 font-mono">{toolsCount}</dd>
            </div>
            {health.python_version != null && (
              <div>
                <dt className="text-slate-500">Python version</dt>
                <dd className="text-slate-200 font-mono">{health.python_version}</dd>
              </div>
            )}
            {health.version != null && (
              <div>
                <dt className="text-slate-500">Version</dt>
                <dd className="text-slate-200 font-mono">{health.version}</dd>
              </div>
            )}
          </dl>
          {memoryPct != null && (
            <div>
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>Memory usage</span>
                <span>{typeof memoryPct === 'number' && memoryPct <= 1 ? `${(memoryPct * 100).toFixed(0)}%` : `${memoryPct} MB`}</span>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-700 overflow-hidden">
                <div
                  className="h-full bg-sky-500 rounded-full transition-all"
                  style={{
                    width: `${Math.min(100, (typeof memoryPct === 'number' && memoryPct <= 1 ? memoryPct : memoryPct / 1024) * 100)}%`,
                  }}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
