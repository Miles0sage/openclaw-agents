import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import type { ObservabilityErrorRatePoint } from '@/types/observability';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { CardShell, SkeletonBlock, timeAgoBadge } from './utils';

function hourLabel(isoHour: string): string {
  const d = new Date(isoHour);
  if (Number.isNaN(d.getTime())) return isoHour;
  return `${String(d.getHours()).padStart(2, '0')}:00`;
}

function colorForRate(pct: number | null): string {
  if (pct == null) return '#64748b';
  if (pct < 5) return '#22c55e';
  if (pct < 20) return '#fbbf24';
  return '#ef4444';
}

export function ErrorRateChart({
  series,
  loading,
  error,
  lastUpdated,
}: {
  series: ObservabilityErrorRatePoint[];
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
}) {
  const data = series.map((p) => ({
    hour: hourLabel(p.hour),
    error_rate: p.error_rate_pct,
    total: p.total,
    failed: p.failed,
  }));

  return (
    <CardShell title="Error rate (last 24h)" right={timeAgoBadge(lastUpdated)}>
      {error && <ErrorBanner message={error} />}
      {loading && series.length === 0 ? (
        <div className="space-y-3">
          <SkeletonBlock className="h-6 w-40" />
          <SkeletonBlock className="h-44 w-full" />
        </div>
      ) : (
        <div className="h-44 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="hour" tick={{ fill: '#94a3b8', fontSize: 10 }} interval={3} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                formatter={(value: number, name) => {
                  if (name === 'error_rate') return [`${(value ?? 0).toFixed(1)}%`, 'Error rate'];
                  return [String(value), name];
                }}
              />
              <Bar dataKey="error_rate" name="Error rate">
                {data.map((entry, i) => (
                  <Cell key={i} fill={colorForRate(entry.error_rate)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-xs text-slate-500">Green &lt; 5%, yellow 5–20%, red &gt; 20%.</p>
    </CardShell>
  );
}

