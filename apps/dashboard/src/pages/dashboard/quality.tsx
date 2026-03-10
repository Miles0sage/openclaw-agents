import { useEffect, useState, useCallback } from 'react';
import { getJudgeSummary } from '@/api/analytics';
import type { JudgeSummary } from '@/types/analytics';
import { QualityChart } from '@/components/analytics/QualityChart';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';

export function QualityPage() {
  const [data, setData] = useState<JudgeSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const refetch = useCallback(() => {
    setError(null);
    setLoading(true);
    getJudgeSummary(7)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(refetch, 30_000);
    return () => clearInterval(id);
  }, [autoRefresh, refetch]);

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-slate-100">Job Quality (last 7 days)</h1>
        <LoadingSpinner label="Loading quality data…" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-slate-100">Job Quality (last 7 days)</h1>
        <ErrorBanner message={error} onRetry={refetch} />
      </div>
    );
  }

  if (!data) return null;

  const hasScores = (data.by_agent?.length ?? 0) > 0 || (data.aggregate_score ?? 0) > 0;

  const exportCsv = () => {
    const rows: string[][] = [
      ['agent_key', 'avg_score', 'count'],
      ...data.by_agent.map((a) => [a.agent_key, String(a.avg_score), String(a.count)]),
      [],
      ['metric', 'value'],
      ['aggregate_score', String(data.aggregate_score)],
      ['pass_count', String(data.pass_count)],
      ['fail_count', String(data.fail_count)],
      ['period_days', String(data.period_days)],
    ];
    if (data.dimensions && Object.keys(data.dimensions).length > 0) {
      rows.push([]);
      rows.push(['dimension', 'score']);
      Object.entries(data.dimensions).forEach(([k, v]) => rows.push([k, String(v)]));
    }
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `quality-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-slate-100">Job Quality (last 7 days)</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600"
          >
            Auto-refresh {autoRefresh ? 'ON' : 'OFF'}
          </button>
          <button
            type="button"
            onClick={exportCsv}
            className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600"
          >
            Export CSV
          </button>
        </div>
      </div>
      {error && <ErrorBanner message={error} onRetry={refetch} />}
      {!hasScores ? (
        <EmptyState title="No quality scores yet" description="Judge scores will appear after jobs complete." />
      ) : (
        <QualityChart data={data} />
      )}
    </div>
  );
}
