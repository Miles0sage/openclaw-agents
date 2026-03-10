import { useEffect, useState, useCallback } from 'react';
import { getAgents } from '@/api/analytics';
import type { AgentStats } from '@/types/analytics';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';
import { ExportButton } from '@/components/ui/ExportButton';

const COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa'];

export function CostBreakdown() {
  const [agents, setAgents] = useState<AgentStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(() => {
    setError(null);
    setLoading(true);
    getAgents()
      .then((res) => setAgents(res.agents ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load cost data'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  if (loading && agents.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <LoadingSpinner label="Loading cost data…" />
      </div>
    );
  }
  if (error && agents.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <ErrorBanner message={error} onRetry={refetch} />
      </div>
    );
  }

  const totalCost = agents.reduce((sum, a) => sum + a.avg_cost_usd * a.total_jobs, 0);
  const pieData = agents.map((a, i) => ({
    name: a.agent_key,
    value: Math.round((a.avg_cost_usd * a.total_jobs) * 1e6) / 1e6,
    color: COLORS[i % COLORS.length],
  })).filter((d) => d.value > 0);

  if (agents.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <EmptyState title="No cost data yet" description="Cost by agent will appear after jobs run." />
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/50 p-4 card-hover animate-slide-up">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-300">Cost by agent</h3>
        <ExportButton
          data={agents}
          filename={`cost-breakdown-${new Date().toISOString().slice(0, 10)}.csv`}
          format="csv"
          label="Export CSV"
        />
      </div>
      {error && <ErrorBanner message={error} onRetry={refetch} />}
      <div className="grid gap-4 md:grid-cols-[280px_1fr] min-w-0">
        {pieData.length > 0 ? (
          <div className="h-64 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={({ name, value }) => `${name}: $${value.toFixed(3)}`}
                >
                  {pieData.map((item, i) => (
                    <Cell key={i} fill={item.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                  formatter={(value: number) => [`$${value.toFixed(4)}`, 'Cost']}
                />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-slate-500 text-sm">No cost data yet</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-slate-600">
                <th className="pb-2 pr-4">Agent</th>
                <th className="pb-2 pr-4">Total cost</th>
                <th className="pb-2 pr-4">Job count</th>
                <th className="pb-2">Cost per job</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => {
                const cost = a.avg_cost_usd * a.total_jobs;
                return (
                  <tr key={a.agent_key} className="border-b border-slate-700/50">
                    <td className="py-2 pr-4 font-mono text-slate-300">{a.agent_key}</td>
                    <td className="py-2 pr-4 text-slate-300">${cost.toFixed(4)}</td>
                    <td className="py-2 pr-4 text-slate-400">{a.total_jobs}</td>
                    <td className="py-2 text-slate-400">${a.avg_cost_usd.toFixed(4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {agents.length > 0 && (
            <p className="text-xs text-slate-500 mt-2">Total: ${totalCost.toFixed(4)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
