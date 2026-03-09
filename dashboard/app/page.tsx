import { JobTable } from "@/components/JobTable";
import { StatCard } from "@/components/StatCard";
import {
  buildOverviewMetrics,
  buildQueueRows,
  fetchActiveJobs,
  fetchAnalyticsJobs,
  fetchCostAnalytics,
  fetchRunnerStats,
  fetchWorkflowJobs,
} from "@/lib/api";
import {
  formatCurrency,
  formatDuration,
  formatNumber,
  formatPercent,
  phaseLabel,
} from "@/lib/format";

export default async function OverviewPage() {
  const [runnerStats, costAnalytics, activeJobs, analyticsJobs, workflowJobs] =
    await Promise.all([
      fetchRunnerStats(),
      fetchCostAnalytics(),
      fetchActiveJobs(),
      fetchAnalyticsJobs(50),
      fetchWorkflowJobs(50),
    ]);

  const queueRows = buildQueueRows(workflowJobs, analyticsJobs);
  const metrics = buildOverviewMetrics(runnerStats, costAnalytics, activeJobs, queueRows);
  const liveStates = Object.entries(activeJobs.jobs).slice(0, 5);

  return (
    <div className="space-y-8">
      <section className="rounded-[2rem] border border-white/10 bg-white/[0.03] px-6 py-7 shadow-panel">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">
          Overview
        </p>
        <h2 className="mt-3 text-4xl font-semibold text-white">
          Live queue, delivery health, and burn rate
        </h2>
        <p className="mt-3 max-w-3xl text-slate-400">
          This dashboard is powered entirely by the existing OpenClaw FastAPI endpoints.
          Where backend payloads are partial, the UI shows empty states instead of breaking.
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Jobs volume"
          value={formatNumber(metrics.todayJobs)}
          detail={`Today ${metrics.todayJobs} • Week ${metrics.weekJobs} • All time ${metrics.allTimeJobs}`}
          accent="text-orange-300"
        />
        <StatCard
          label="Success rate"
          value={formatPercent(metrics.successRate)}
          detail={`Average duration ${formatDuration(metrics.avgDurationSeconds)}`}
          accent="text-cyan-300"
        />
        <StatCard
          label="Total cost"
          value={formatCurrency(metrics.totalCost)}
          detail={`${Object.keys(costAnalytics.by_agent).length} agents contributed tracked cost`}
          accent="text-emerald-300"
        />
        <StatCard
          label="Active jobs"
          value={formatNumber(metrics.activeJobs)}
          detail={`${liveStates.length} live states currently visible`}
          accent="text-violet-300"
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
        <div className="rounded-[2rem] border border-white/10 bg-white/[0.03] p-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-orange-300">
                Queue
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">Recent jobs</h2>
            </div>
          </div>
          <JobTable rows={queueRows.slice(0, 8)} emptyMessage="No data" />
        </div>

        <div className="rounded-[2rem] border border-white/10 bg-white/[0.03] p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">
            Live states
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-white">Currently active jobs</h2>
          <div className="mt-6 space-y-4">
            {liveStates.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-white/15 bg-slate-950/40 px-5 py-12 text-center text-sm text-slate-400">
                No data
              </div>
            ) : (
              liveStates.map(([jobId, state]) => (
                <div
                  key={jobId}
                  className="rounded-3xl border border-white/8 bg-slate-950/50 p-4"
                >
                  <p className="font-mono text-xs text-cyan-200">{jobId}</p>
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <span className="text-lg font-medium text-white">
                      {phaseLabel(state.phase || "research")}
                    </span>
                    <span className="text-sm text-slate-400">
                      {Math.round(state.progress_pct || 0)}%
                    </span>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-white/5">
                    <div
                      className="h-2 rounded-full bg-gradient-to-r from-cyan-400 to-orange-400"
                      style={{ width: `${state.progress_pct || 0}%` }}
                    />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-400">
                    <span>{formatCurrency(state.cost_usd || 0)}</span>
                    <span>{(state.active_tools || []).length} active tools</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
