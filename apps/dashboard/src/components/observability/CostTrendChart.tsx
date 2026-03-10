import {
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import type { ObservabilityCostPoint } from '@/types/observability';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { CardShell, SkeletonBlock, timeAgoBadge } from './utils';

export function CostTrendChart({
  series,
  loading,
  error,
  lastUpdated,
}: {
  series: ObservabilityCostPoint[];
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
}) {
  const data = series.map((d) => ({
    day: d.day.slice(5),
    total: d.total_cost_usd,
    avg: d.avg_cost_usd,
  }));

  return (
    <CardShell title="Cost trend (last 7d)" right={timeAgoBadge(lastUpdated)}>
      {error && <ErrorBanner message={error} />}
      {loading && series.length === 0 ? (
        <div className="space-y-3">
          <SkeletonBlock className="h-6 w-40" />
          <SkeletonBlock className="h-52 w-full" />
        </div>
      ) : (
        <div className="h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="day" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis yAxisId="left" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                tickFormatter={(v: number) => (v == null ? '—' : `$${Number(v).toFixed(3)}`)}
              />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                formatter={(value: number, name: string) => {
                  if (name === 'total') return [`$${Number(value).toFixed(4)}`, 'Total cost'];
                  if (name === 'avg') return [`$${Number(value).toFixed(5)}`, 'Avg cost/job'];
                  return [String(value), name];
                }}
              />
              <Legend />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="total"
                name="Total cost"
                stroke="#38bdf8"
                fill="#38bdf8"
                fillOpacity={0.25}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="avg"
                name="Avg cost/job"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-xs text-slate-500">
        If job-level costs aren’t available yet, avg cost/job may be unavailable.
      </p>
    </CardShell>
  );
}

