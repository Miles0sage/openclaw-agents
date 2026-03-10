import { LiveJobMonitor } from '@/components/analytics/LiveJobMonitor';

export function LivePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-100">Live Job Monitor</h1>
      <p className="text-slate-400 text-sm">
        Enter a job ID and connect to stream phase transitions, tool calls, and cost in real time.
      </p>
      <LiveJobMonitor />
    </div>
  );
}
