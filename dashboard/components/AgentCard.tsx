import { formatCurrency, formatDuration, formatPercent, humanizeAgentName } from "@/lib/format";
import type { AgentStats } from "@/lib/types";

interface AgentCardProps {
  agentKey: string;
  stats: AgentStats;
}

export function AgentCard({ agentKey, stats }: AgentCardProps) {
  return (
    <article className="rounded-3xl border border-white/10 bg-white/[0.03] p-6 shadow-panel">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">Agent</p>
          <h2 className="mt-2 text-2xl font-semibold text-white">{humanizeAgentName(agentKey)}</h2>
        </div>
        <span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs text-cyan-100">
          {stats.jobs} jobs
        </span>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-white/8 bg-slate-950/40 p-4">
          <p className="text-sm text-slate-400">Success rate</p>
          <p className="mt-2 text-2xl font-semibold text-white">{formatPercent(stats.success_rate)}</p>
        </div>
        <div className="rounded-2xl border border-white/8 bg-slate-950/40 p-4">
          <p className="text-sm text-slate-400">Avg cost</p>
          <p className="mt-2 text-2xl font-semibold text-white">{formatCurrency(stats.avg_cost)}</p>
        </div>
        <div className="rounded-2xl border border-white/8 bg-slate-950/40 p-4">
          <p className="text-sm text-slate-400">Avg duration</p>
          <p className="mt-2 text-2xl font-semibold text-white">{formatDuration(stats.avg_duration)}</p>
        </div>
        <div className="rounded-2xl border border-white/8 bg-slate-950/40 p-4">
          <p className="text-sm text-slate-400">Failures</p>
          <p className="mt-2 text-2xl font-semibold text-white">{stats.failed}</p>
        </div>
      </div>
    </article>
  );
}
