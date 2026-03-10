import { useEffect, useState, useCallback } from 'react';
import { getTracesRecent } from '@/api/analytics';
import type { TraceListItem } from '@/types/analytics';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';
import { ExportButton } from '@/components/ui/ExportButton';

const BAR_HEIGHT = 20;
const GAP = 4;
const PADDING = 8;

export function JobTimeline() {
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(() => {
    setError(null);
    setLoading(true);
    getTracesRecent(20)
      .then((res) => setTraces(res.traces))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load traces'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  if (loading && traces.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-3">
        <h3 className="text-sm font-medium text-slate-300">Recent jobs (timeline)</h3>
        <LoadingSpinner label="Loading timeline…" />
      </div>
    );
  }
  if (error && traces.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-3">
        <h3 className="text-sm font-medium text-slate-300">Recent jobs (timeline)</h3>
        <ErrorBanner message={error} onRetry={refetch} />
      </div>
    );
  }
  if (traces.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-3">
        <h3 className="text-sm font-medium text-slate-300">Recent jobs (timeline)</h3>
        <EmptyState title="No recent jobs" description="Job timeline will appear here." />
      </div>
    );
  }

  const maxDuration = Math.max(...traces.map((t) => t.duration_ms), 1);
  const totalHeight = traces.length * (BAR_HEIGHT + GAP) + PADDING * 2;
  const width = 400;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-300">Recent jobs (timeline)</h3>
        <ExportButton
          data={traces}
          filename={`job-timeline-${new Date().toISOString().slice(0, 10)}.json`}
          format="json"
          label="Export JSON"
        />
      </div>
      {error && <ErrorBanner message={error} onRetry={refetch} />}
      <div className="overflow-x-auto">
        <svg
          width={width}
          height={totalHeight}
          className="min-w-[400px]"
          aria-label="Job timeline"
        >
          {traces.map((t, i) => {
            const y = PADDING + i * (BAR_HEIGHT + GAP);
            const barWidth = Math.max(4, (t.duration_ms / maxDuration) * (width - PADDING * 2 - 40));
            const success = t.status !== 'error' && t.status !== 'failed';
            const fill = success ? '#22c55e' : '#ef4444';
            const id = t.job_id ?? t.trace_id;
            const isHovered = hovered === id;
            return (
              <g
                key={t.trace_id}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}
              >
                <rect
                  x={PADDING}
                  y={y}
                  width={barWidth}
                  height={BAR_HEIGHT}
                  rx={3}
                  fill={fill}
                  opacity={isHovered ? 1 : 0.85}
                  stroke={isHovered ? '#94a3b8' : 'transparent'}
                  strokeWidth={1}
                />
                <text
                  x={PADDING + barWidth + 6}
                  y={y + BAR_HEIGHT / 2 + 4}
                  fontSize={10}
                  fill="#94a3b8"
                  className="font-mono"
                >
                  {t.job_id}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {hovered && (
        <div className="text-xs text-slate-400 border border-slate-600 rounded px-2 py-1.5 bg-slate-800/80">
          {(() => {
            const t = traces.find((x) => (x.job_id ?? x.trace_id) === hovered);
            if (!t) return null;
            return (
              <>
                <p className="font-mono text-slate-200">{t.job_id}</p>
                <p>Duration: {t.duration_ms}ms</p>
                <p>Status: {t.status ?? '—'}</p>
                <p>Started: {t.start_time ? new Date(t.start_time).toLocaleString() : '—'}</p>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
