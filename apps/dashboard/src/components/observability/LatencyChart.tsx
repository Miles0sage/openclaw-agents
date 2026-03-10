import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { ObservabilityLatencyPoint } from '@/types/observability';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { CardShell, SkeletonBlock, timeAgoBadge } from './utils';

function hourLabel(isoHour: string): string {
  const d = new Date(isoHour);
  if (Number.isNaN(d.getTime())) return isoHour;
  return `${String(d.getHours()).padStart(2, '0')}:00`;
}

export function LatencyChart({
  series,
  loading,
  error,
  lastUpdated,
}: {
  series: ObservabilityLatencyPoint[];
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
}) {
  const data = series.map((p) => ({
    hour: hourLabel(p.hour),
    p50: p.p50_min,
    p95: p.p95_min,
    n: p.sample_count,
  }));

  return (
    <CardShell title="Job latency (last 24h)" right={timeAgoBadge(lastUpdated)}>
      {error && <ErrorBanner message={error} />}
      {loading && series.length === 0 ? (
        <div className="space-y-3">
          <SkeletonBlock className="h-6 w-44" />
          <SkeletonBlock className="h-44 w-full" />
        </div>
      ) : (
        <div className="h-44 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="hour" tick={{ fill: '#94a3b8', fontSize: 10 }} interval={3} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                formatter={(value: number) => (value == null ? ['—', ''] : [`${value.toFixed(1)} min`, ''])}
              />
              <Legend />
              <Line type="monotone" dataKey="p50" stroke="#38bdf8" dot={false} name="p50" strokeWidth={2} />
              <Line
                type="monotone"
                dataKey="p95"
                stroke="#fbbf24"
                dot={false}
                name="p95"
                strokeDasharray="4 4"
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-xs text-slate-500">Computed from completion durations (minutes).</p>
    </CardShell>
  );
}

