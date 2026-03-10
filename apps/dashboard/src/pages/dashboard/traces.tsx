import { useEffect, useState } from 'react';
import { getTraces, getTrace } from '@/api/analytics';
import type { TraceListItem, TraceDetail } from '@/types/analytics';
import { TraceWaterfall } from '@/components/analytics/TraceWaterfall';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';

export function TracesPage() {
  const [list, setList] = useState<TraceListItem[]>([]);
  const [selected, setSelected] = useState<TraceDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const filteredList = filter.trim()
    ? list.filter(
        (t) =>
          t.job_id.toLowerCase().includes(filter.toLowerCase()) ||
          (t.name && t.name.toLowerCase().includes(filter.toLowerCase())),
      )
    : list;

  useEffect(() => {
    let cancelled = false;
    setLoadingList(true);
    getTraces(50)
      .then((res) => {
        if (!cancelled) setList(res.traces);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load traces');
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => { cancelled = true; };
  }, []);

  const onSelectTrace = (jobId: string) => {
    setSelected(null);
    setError(null);
    setLoadingDetail(true);
    getTrace(jobId)
      .then(setSelected)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load trace'))
      .finally(() => setLoadingDetail(false));
  };

  const exportJson = () => {
    const payload = { traces: list, selected: selected ?? null, exportedAt: new Date().toISOString() };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `traces-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const refetch = () => {
    setError(null);
    setLoadingList(true);
    getTraces(50)
      .then((res) => setList(res.traces))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load traces'))
      .finally(() => setLoadingList(false));
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-100">Trace Explorer</h1>

      {error && <ErrorBanner message={error} onRetry={refetch} />}

      {loadingList && list.length === 0 ? (
        <LoadingSpinner label="Loading traces…" />
      ) : list.length === 0 && !error ? (
        <EmptyState title="No traces yet" description="Job traces will appear after runs." />
      ) : list.length > 0 ? (
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 overflow-auto max-h-[70vh]">
          <div className="mb-2 flex flex-col gap-2">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by job_id or name…"
              className="w-full rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 placeholder-slate-500"
            />
            <button
              type="button"
              onClick={exportJson}
              className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-600"
            >
              Export JSON
            </button>
          </div>
          <h2 className="mb-2 text-sm font-medium text-slate-300">Recent traces</h2>
          {loadingList ? (
            <LoadingSpinner label="Loading…" />
          ) : filteredList.length === 0 ? (
            <EmptyState title={list.length === 0 ? 'No traces' : 'No matches'} description={list.length === 0 ? undefined : 'Try a different filter.'} />
          ) : (
            <ul className="space-y-1">
              {filteredList.map((t) => (
                <li key={t.trace_id}>
                  <button
                    type="button"
                    onClick={() => onSelectTrace(t.job_id)}
                    className="w-full text-left rounded px-2 py-1.5 text-sm font-mono text-slate-300 hover:bg-slate-700 focus:bg-slate-700 truncate"
                    title={t.job_id}
                  >
                    {t.job_id}
                  </button>
                  <div className="text-xs text-slate-500 pl-2">{t.duration_ms}ms</div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-w-0">
          {loadingDetail && (
            <div className="flex items-center justify-center py-12 text-slate-400">Loading trace…</div>
          )}
          {!loadingDetail && selected && (
            <TraceWaterfall trace={selected} />
          )}
          {!loadingDetail && !selected && !loadingList && list.length > 0 && (
            <p className="text-slate-500 text-sm py-8">Select a trace from the list</p>
          )}
        </div>
      </div>
      ) : null}
    </div>
  );
}
