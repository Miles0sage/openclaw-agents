import type { JudgeSummary } from '@/types/analytics';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Legend,
} from 'recharts';

const PASS_THRESHOLD = 0.6;

interface QualityChartProps {
  data: JudgeSummary;
}

export function QualityChart({ data }: QualityChartProps) {
  const barData = data.by_agent.map((a) => ({
    name: a.agent_key.replace(/_/g, ' '),
    score: a.avg_score,
    count: a.count,
  }));

  const radarData = Object.entries(data.dimensions ?? {}).map(([key, value]) => ({
    dimension: key,
    value,
    fullMark: 1,
  }));

  return (
    <div className="space-y-6 stagger-children">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 card-hover transition-all duration-200">
          <h3 className="mb-2 text-sm font-medium text-slate-300">Pass / Fail (threshold {PASS_THRESHOLD})</h3>
          <div className="flex items-baseline gap-4">
            <span className="text-2xl font-bold text-emerald-400">{data.pass_count}</span>
            <span className="text-slate-400">pass</span>
            <span className="text-2xl font-bold text-rose-400">{data.fail_count}</span>
            <span className="text-slate-400">fail</span>
          </div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 card-hover transition-all duration-200">
          <h3 className="mb-2 text-sm font-medium text-slate-300">Aggregate score (last {data.period_days} days)</h3>
          <div className="text-2xl font-bold text-sky-400">
            {(data.aggregate_score * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 card-hover transition-all duration-200">
        <h3 className="mb-3 text-sm font-medium text-slate-300">Score by agent</h3>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={barData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <YAxis domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155' }}
                labelStyle={{ color: '#cbd5e1' }}
              />
              <Bar dataKey="score" fill="#38bdf8" name="Avg score" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {radarData.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 card-hover transition-all duration-200">
          <h3 className="mb-3 text-sm font-medium text-slate-300">Dimension scores</h3>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData}>
                <PolarGrid stroke="#475569" />
                <PolarAngleAxis dataKey="dimension" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <PolarRadiusAxis angle={90} domain={[0, 1]} tick={{ fill: '#94a3b8' }} />
                <Radar name="Score" dataKey="value" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.3} />
                <Legend />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
