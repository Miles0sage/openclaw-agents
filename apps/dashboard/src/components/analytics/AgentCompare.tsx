import { useEffect, useState, useCallback } from 'react';
import { getAgents } from '@/api/analytics';
import type { AgentStats } from '@/types/analytics';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';

export function AgentCompare() {
  const [agents, setAgents] = useState<AgentStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agentA, setAgentA] = useState<string>('');
  const [agentB, setAgentB] = useState<string>('');

  const refetch = useCallback(() => {
    setError(null);
    setLoading(true);
    getAgents()
      .then((res) => {
        const agentList = res.agents ?? [];
        setAgents(agentList);
        setAgentA((prev) => prev || (agentList[0]?.agent_key ?? ''));
        setAgentB((prev) => prev || (agentList[1]?.agent_key ?? ''));
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load agents'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  useEffect(() => {
    if (agents.length >= 2 && agentA && !agentB && agents.some((a) => a.agent_key === agentA)) {
      const other = agents.find((a) => a.agent_key !== agentA);
      if (other) setAgentB(other.agent_key);
    }
  }, [agents, agentA, agentB]);

  if (loading && agents.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <LoadingSpinner label="Loading agents…" />
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
  if (agents.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <EmptyState title="No agents yet" description="Agent stats will appear after jobs run." />
      </div>
    );
  }

  const a = agents.find((x) => x.agent_key === agentA);
  const b = agents.find((x) => x.agent_key === agentB);
  const compareData =
    a && b
      ? [
          { metric: 'Success rate', [a.agent_key]: a.success_rate, [b.agent_key]: b.success_rate },
          { metric: 'Avg cost ($)', [a.agent_key]: a.avg_cost_usd, [b.agent_key]: b.avg_cost_usd },
          { metric: 'Total jobs', [a.agent_key]: a.total_jobs, [b.agent_key]: b.total_jobs },
        ]
      : [];

  return (
    <div className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/50 p-4">
      <h3 className="text-sm font-medium text-slate-300">Compare agents</h3>
      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2">
          <span className="text-slate-400 text-sm">Agent A</span>
          <select
            value={agentA}
            onChange={(e) => setAgentA(e.target.value)}
            className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-sm px-2 py-1"
          >
            {agents.map((ag) => (
              <option key={ag.agent_key} value={ag.agent_key}>
                {ag.agent_key}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-slate-400 text-sm">Agent B</span>
          <select
            value={agentB}
            onChange={(e) => setAgentB(e.target.value)}
            className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-sm px-2 py-1"
          >
            {agents.map((ag) => (
              <option key={ag.agent_key} value={ag.agent_key}>
                {ag.agent_key}
              </option>
            ))}
          </select>
        </label>
      </div>

      {a && b && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded border border-slate-600 bg-slate-800/30 p-3">
              <p className="font-mono text-sky-400 text-sm mb-2">{a.agent_key}</p>
              <ul className="text-xs text-slate-400 space-y-1">
                <li>Success rate: {(a.success_rate * 100).toFixed(1)}%</li>
                <li>Avg cost: ${a.avg_cost_usd.toFixed(4)}</li>
                <li>Total jobs: {a.total_jobs}</li>
                <li>Favorite tools: {a.favorite_tools.join(', ') || '—'}</li>
              </ul>
            </div>
            <div className="rounded border border-slate-600 bg-slate-800/30 p-3">
              <p className="font-mono text-emerald-400 text-sm mb-2">{b.agent_key}</p>
              <ul className="text-xs text-slate-400 space-y-1">
                <li>Success rate: {(b.success_rate * 100).toFixed(1)}%</li>
                <li>Avg cost: ${b.avg_cost_usd.toFixed(4)}</li>
                <li>Total jobs: {b.total_jobs}</li>
                <li>Favorite tools: {b.favorite_tools.join(', ') || '—'}</li>
              </ul>
            </div>
          </div>

          {compareData.length > 0 && (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={compareData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="metric" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                    labelStyle={{ color: '#cbd5e1' }}
                  />
                  <Legend />
                  <Bar dataKey={a.agent_key} fill="#38bdf8" name={a.agent_key} radius={[4, 4, 0, 0]} />
                  <Bar dataKey={b.agent_key} fill="#34d399" name={b.agent_key} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
