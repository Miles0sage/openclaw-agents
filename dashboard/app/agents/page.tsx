import { AgentCard } from "@/components/AgentCard";
import { fetchAgentAnalytics } from "@/lib/api";

export default async function AgentsPage() {
  const analytics = await fetchAgentAnalytics();
  const entries = Object.entries(analytics.agent_stats).sort(
    (left, right) => right[1].jobs - left[1].jobs,
  );

  return (
    <div className="space-y-8">
      <section className="rounded-[2rem] border border-white/10 bg-white/[0.03] px-6 py-7 shadow-panel">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">
          Agents
        </p>
        <h2 className="mt-3 text-4xl font-semibold text-white">Performance by agent</h2>
        <p className="mt-3 max-w-3xl text-slate-400">
          Cards are populated from `/api/analytics/agents` and stay empty when there is no
          event history yet.
        </p>
      </section>

      {entries.length === 0 ? (
        <div className="rounded-[2rem] border border-dashed border-white/15 bg-white/[0.03] px-6 py-20 text-center text-sm text-slate-400">
          No data
        </div>
      ) : (
        <section className="grid gap-6 lg:grid-cols-2">
          {entries.map(([agentKey, stats]) => (
            <AgentCard key={agentKey} agentKey={agentKey} stats={stats} />
          ))}
        </section>
      )}
    </div>
  );
}
