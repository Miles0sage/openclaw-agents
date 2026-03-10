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
import type { JobStats } from '@/types/observability';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { CardShell, SkeletonBlock, timeAgoBadge } from './utils';

export function QueueDepthCard({
  queueStats,
  loading,
  error,
  lastUpdated,
}: {
  queueStats: JobStats | null;
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
}) {
  const data = [
    {
      name: 'Now',
      pending: queueStats?.pending ?? 0,
      running: queueStats?.running ?? 0,
      failed: queueStats?.failed ?? 0,
      dlq: queueStats?.dlq ?? 0,
    },
  ];

  return (
    <CardShell title="Queue depth" right={timeAgoBadge(lastUpdated)}>
      {error && <ErrorBanner message={error} />}
      {loading && !queueStats ? (
        <div className="space-y-3">
          <SkeletonBlock className="h-6 w-40" />
          <SkeletonBlock className="h-40 w-full" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div className="rounded border border-slate-600 bg-slate-800/30 p-2">
              <div className="text-slate-500">Pending</div>
              <div className="text-slate-200 font-mono">{queueStats?.pending ?? '—'}</div>
            </div>
            <div className="rounded border border-slate-600 bg-slate-800/30 p-2">
              <div className="text-slate-500">Running</div>
              <div className="text-slate-200 font-mono">{queueStats?.running ?? '—'}</div>
            </div>
            <div className="rounded border border-slate-600 bg-slate-800/30 p-2">
              <div className="text-slate-500">Failed</div>
              <div className="text-slate-200 font-mono">{queueStats?.failed ?? '—'}</div>
            </div>
            <div className="rounded border border-slate-600 bg-slate-800/30 p-2">
              <div className="text-slate-500">DLQ</div>
              <div className="text-slate-200 font-mono">{queueStats?.dlq ?? '—'}</div>
            </div>
          </div>

          <div className="h-40 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                  labelStyle={{ color: '#cbd5e1' }}
                />
                <Legend />
                <Bar dataKey="pending" stackId="a" fill="#fbbf24" name="Pending" />
                <Bar dataKey="running" stackId="a" fill="#38bdf8" name="Running" />
                <Bar dataKey="failed" stackId="a" fill="#f87171" name="Failed" />
                <Bar dataKey="dlq" stackId="a" fill="#7f1d1d" name="DLQ" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </CardShell>
  );
}

