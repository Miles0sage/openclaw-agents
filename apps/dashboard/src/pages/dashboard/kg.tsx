import { useEffect, useState, useCallback } from 'react';
import { getKgSummary } from '@/api/analytics';
import type { KgSummary } from '@/types/analytics';
import { KnowledgeGraph } from '@/components/analytics/KnowledgeGraph';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';
import { ExportButton } from '@/components/ui/ExportButton';

export function KgPage() {
  const [summary, setSummary] = useState<KgSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(() => {
    setError(null);
    setLoading(true);
    getKgSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  if (loading && !summary) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-slate-100">Knowledge Graph</h1>
        <LoadingSpinner label="Loading knowledge graph…" />
      </div>
    );
  }

  if (error && !summary) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-slate-100">Knowledge Graph</h1>
        <ErrorBanner message={error} onRetry={refetch} />
      </div>
    );
  }

  if (!summary) return null;

  const hasData = (summary.tools?.length ?? 0) > 0 || (summary.agents?.length ?? 0) > 0 || (summary.edges?.length ?? 0) > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-slate-100">Knowledge Graph</h1>
        <ExportButton
          data={summary}
          filename={`kg-summary-${new Date().toISOString().slice(0, 10)}.json`}
          format="json"
          label="Export JSON"
        />
      </div>
      {error && <ErrorBanner message={error} onRetry={refetch} />}
      {!hasData ? (
        <EmptyState title="No knowledge graph data yet" description="Tool and agent stats will appear after jobs run." />
      ) : (
        <KnowledgeGraph summary={summary} />
      )}
    </div>
  );
}
