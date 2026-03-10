import { useMemo } from 'react';
import { useObservabilityData } from '@/hooks/useObservabilityData';
import { QueueDepthCard } from '@/components/observability/QueueDepthCard';
import { LatencyChart } from '@/components/observability/LatencyChart';
import { ErrorRateChart } from '@/components/observability/ErrorRateChart';
import { CostTrendChart } from '@/components/observability/CostTrendChart';
import { WorkerHealthCard } from '@/components/observability/WorkerHealthCard';

export function ObservabilityTab() {
  const data = useObservabilityData();

  const anyLoading = useMemo(
    () => Object.values(data.isLoading).some(Boolean),
    [data.isLoading]
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Observability</h1>
          <p className="text-slate-400 text-sm">
            Queue depth, latency, error rate, cost/job, and worker health.
          </p>
        </div>
        <button
          type="button"
          onClick={data.refetch}
          className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:opacity-60"
          disabled={anyLoading}
        >
          Refresh
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 stagger-children">
        <QueueDepthCard
          queueStats={data.queueStats}
          loading={data.isLoading.queue}
          error={data.errors.queue}
          lastUpdated={data.lastUpdated.queue}
        />
        <WorkerHealthCard
          health={data.health}
          dlq={data.dlq}
          loading={data.isLoading.health}
          error={data.errors.health}
          lastUpdated={data.lastUpdated.health}
          dlqError={data.errors.dlq}
        />
        <LatencyChart
          series={data.latencySeries}
          loading={data.isLoading.jobs}
          error={data.errors.jobs}
          lastUpdated={data.lastUpdated.jobs}
        />
        <ErrorRateChart
          series={data.errorRateSeries}
          loading={data.isLoading.jobs}
          error={data.errors.jobs}
          lastUpdated={data.lastUpdated.jobs}
        />
        <div className="lg:col-span-2">
          <CostTrendChart
            series={data.costTrend}
            loading={false}
            error={data.errors.costs}
            lastUpdated={data.lastUpdated.costs ?? data.lastUpdated.jobs}
          />
        </div>
      </div>
    </div>
  );
}

