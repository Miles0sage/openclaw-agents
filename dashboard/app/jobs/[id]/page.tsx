import { CostChart } from "@/components/CostChart";
import { LogStream } from "@/components/LogStream";
import { PhaseTimeline } from "@/components/PhaseTimeline";
import {
  buildPhaseCostSeries,
  buildPhaseRows,
  buildQueueRows,
  fetchAnalyticsJobs,
  fetchJobCosts,
  fetchJobPhases,
  fetchJobQuality,
  fetchLiveJob,
  fetchWorkflowJobs,
} from "@/lib/api";
import {
  formatCurrency,
  formatPercent,
  getActivePhaseLabel,
  humanizeAgentName,
  phaseLabel,
  truncateText,
} from "@/lib/format";

interface JobDetailPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function JobDetailPage({ params }: JobDetailPageProps) {
  const { id } = await params;
  const [phasesResponse, costsResponse, qualityResponse, liveJob, analyticsJobs, workflowJobs] =
    await Promise.all([
      fetchJobPhases(id),
      fetchJobCosts(id),
      fetchJobQuality(id),
      fetchLiveJob(id),
      fetchAnalyticsJobs(50),
      fetchWorkflowJobs(200),
    ]);

  const queueRows = buildQueueRows(workflowJobs, analyticsJobs);
  const job = queueRows.find((row) => row.jobId === id);
  const phases = buildPhaseRows(phasesResponse, liveJob);
  const chartData = buildPhaseCostSeries(costsResponse);
  const qualityScore = qualityResponse.overall_score ?? qualityResponse.score ?? null;

  return (
    <div className="space-y-8">
      <section className="rounded-[2rem] border border-white/10 bg-white/[0.03] px-6 py-7 shadow-panel">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">
          Job Detail
        </p>
        <div className="mt-4 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-4xl">
            <h2 className="text-4xl font-semibold text-white">
              {job?.project || "Unknown project"}
            </h2>
            <p className="mt-3 font-mono text-sm text-cyan-200">{id}</p>
            <p className="mt-4 text-slate-300">
              {job ? truncateText(job.task, 220) : "No data"}
            </p>
          </div>
          <div className="grid gap-3 rounded-3xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
            <div>
              <span className="text-slate-500">Active phase</span>
              <p className="mt-1 text-lg font-semibold text-white">{getActivePhaseLabel(phases)}</p>
            </div>
            <div>
              <span className="text-slate-500">Agent</span>
              <p className="mt-1 text-lg font-semibold text-white">
                {humanizeAgentName(job?.agent)}
              </p>
            </div>
            <div>
              <span className="text-slate-500">Tracked cost</span>
              <p className="mt-1 text-lg font-semibold text-white">
                {formatCurrency(costsResponse.costs.total_cost)}
              </p>
            </div>
            <div>
              <span className="text-slate-500">Quality score</span>
              <p className="mt-1 text-lg font-semibold text-white">
                {qualityScore === null ? "No data" : formatPercent(qualityScore * 100)}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <PhaseTimeline phases={phases} />
        <CostChart title="Cost by phase" data={chartData} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <LogStream jobId={id} />

        <div className="rounded-[2rem] border border-white/10 bg-white/[0.03] p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-orange-300">
            Quality
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-white">
            Review signal
          </h2>
          {qualityResponse.dimensions?.length ? (
            <div className="mt-6 space-y-4">
              {qualityResponse.dimensions.map((dimension) => (
                <div
                  key={dimension.dimension}
                  className="rounded-3xl border border-white/8 bg-slate-950/40 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-lg font-medium text-white">
                      {phaseLabel(dimension.dimension)}
                    </span>
                    <span className="text-sm text-slate-400">
                      {formatPercent(dimension.score * 100)}
                    </span>
                  </div>
                  <p className="mt-3 text-sm text-slate-400">{dimension.reasoning}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-6 rounded-3xl border border-dashed border-white/15 bg-slate-950/40 px-5 py-12 text-center text-sm text-slate-400">
              No data
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
