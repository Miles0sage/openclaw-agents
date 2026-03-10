import { AgentCompare } from '@/components/analytics/AgentCompare';
import { CostBreakdown } from '@/components/analytics/CostBreakdown';

export function InsightsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-100">Insights</h1>
      <AgentCompare />
      <CostBreakdown />
    </div>
  );
}
