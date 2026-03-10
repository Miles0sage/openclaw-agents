import { SystemHealth } from '@/components/analytics/SystemHealth';
import { JobTimeline } from '@/components/analytics/JobTimeline';
import { AgentHealthGrid } from '@/components/analytics/AgentHealthGrid';

export function SystemPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-100">System</h1>
      <AgentHealthGrid />
      <SystemHealth />
      <JobTimeline />
    </div>
  );
}
