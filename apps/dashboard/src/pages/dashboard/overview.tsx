import { useState, useEffect, useCallback } from 'react';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';
import { ExportButton } from '@/components/ui/ExportButton';
import { getAgents, getTracesRecent } from '@/api/analytics';
import type { AgentStats, TraceListItem } from '@/types/analytics';

export function OverviewPage() {
  const [agents, setAgents] = useState<AgentStats[]>([]);
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setError(null);
    try {
      const [agentRes, traceRes] = await Promise.all([
        getAgents(),
        getTracesRecent(10),
      ]);
      setAgents(agentRes.agents ?? []);
      setTraces(traceRes.traces ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load overview');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchData]);

  if (loading && agents.length === 0 && traces.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold text-slate-100">Overview</h1>
        <LoadingSpinner label="Loading overview…" />
      </div>
    );
  }

  if (error && agents.length === 0 && traces.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold text-slate-100">Overview</h1>
        <ErrorBanner message={error} onRetry={fetchData} />
      </div>
    );
  }

  const hasAgents = agents.length > 0;
  const hasTraces = traces.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl font-semibold text-slate-100">Overview</h1>
        <div className="flex items-center gap-2">
          {hasAgents && (
            <ExportButton
              data={agents}
              filename={`overview-agents-${new Date().toISOString().slice(0, 10)}.csv`}
              format="csv"
              label="Export agents CSV"
            />
          )}
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            className={`rounded px-3 py-1.5 text-xs font-medium ${
              autoRefresh
                ? 'bg-emerald-600/20 text-emerald-400 border border-emerald-600'
                : 'bg-slate-700 text-slate-400 border border-slate-600'
            }`}
          >
            Auto-refresh: {autoRefresh ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={fetchData} />}

      <div>
        <h2 className="mb-3 text-sm font-medium text-slate-300">Agents</h2>
        {hasAgents ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((a, i) => (
              <div key={(a.agent_key as string) ?? i} className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
                <p className="font-mono text-sm text-slate-200">{String(a.agent_key ?? '—')}</p>
                <p className="text-xs text-slate-400 mt-1">Jobs: {Number(a.total_jobs ?? 0)}</p>
                <p className="text-xs text-slate-400">Success: {((Number(a.success_rate ?? 0)) * 100).toFixed(0)}%</p>
                <p className="text-xs text-slate-400">Avg cost: ${Number(a.avg_cost_usd ?? 0).toFixed(4)}</p>
                <p className="text-xs text-slate-500 truncate mt-1">
                  Tools: {Array.isArray(a.favorite_tools) ? a.favorite_tools.join(', ') : '—'}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No agents yet" description="Agent stats will appear after jobs run." />
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium text-slate-300">Recent Traces</h2>
        {hasTraces ? (
          <>
            <div className="mb-2 flex justify-end">
              <ExportButton
                data={traces}
                filename={`overview-traces-${new Date().toISOString().slice(0, 10)}.json`}
                format="json"
                label="Export JSON"
              />
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-slate-700">
                    <th className="p-3">Trace ID</th>
                    <th className="p-3">Operation</th>
                    <th className="p-3">Duration</th>
                    <th className="p-3">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {traces.map((t, i) => (
                    <tr key={(t.trace_id as string) ?? i} className="border-b border-slate-700/50">
                      <td className="p-3 font-mono text-sky-400 text-xs">{String(t.trace_id ?? '').slice(0, 12)}...</td>
                      <td className="p-3 text-slate-300">{t.name ?? '—'}</td>
                      <td className="p-3 text-slate-400">{t.duration_ms ?? 0}ms</td>
                      <td className="p-3 text-slate-500 text-xs">{t.start_time ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <EmptyState title="No traces yet" description="Recent job traces will appear here." />
        )}
      </div>
    </div>
  );
}
