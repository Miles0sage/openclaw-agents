import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAgentHealth } from '@/hooks/useAgentHealth';
import type { AgentHealth, AgentState } from '@/hooks/useAgentHealth';
import { ErrorBanner } from '@/components/ui/ErrorBanner';
import { EmptyState } from '@/components/ui/EmptyState';

function formatTimeAgo(iso: string): string {
  const d = new Date(iso);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (Number.isNaN(sec)) return '—';
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}min ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

const stateMeta: Record<
  AgentState,
  { label: string; dot: string; badge: string; border: string; subtle: string }
> = {
  open: {
    label: 'CIRCUIT OPEN',
    dot: 'bg-red-500',
    badge: 'bg-red-500/20 text-red-300 border border-red-500/30',
    border: 'border-red-500/50',
    subtle: 'text-red-200',
  },
  degraded: {
    label: 'DEGRADED',
    dot: 'bg-amber-500',
    badge: 'bg-amber-500/20 text-amber-200 border border-amber-500/30',
    border: 'border-amber-500/50',
    subtle: 'text-amber-100',
  },
  healthy: {
    label: 'HEALTHY',
    dot: 'bg-green-500',
    badge: 'bg-green-500/15 text-green-200 border border-green-500/25',
    border: 'border-green-500/30',
    subtle: 'text-green-100',
  },
};

function SkeletonCard({ i }: { i: number }) {
  return (
    <div
      key={i}
      className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 animate-pulse"
      aria-hidden
    >
      <div className="flex items-center gap-2">
        <div className="h-2.5 w-2.5 rounded-full bg-slate-600" />
        <div className="h-4 w-32 rounded bg-slate-700" />
      </div>
      <div className="mt-3 h-6 w-28 rounded bg-slate-700" />
      <div className="mt-3 h-4 w-44 rounded bg-slate-700" />
      <div className="mt-2 h-3.5 w-20 rounded bg-slate-700" />
    </div>
  );
}

function AgentHealthCard({
  agent,
  onViewAlerts,
}: {
  agent: AgentHealth;
  onViewAlerts?: (agentKey: string) => void;
}) {
  const meta = stateMeta[agent.state];
  const clickable = agent.state !== 'healthy';

  return (
    <button
      type="button"
      onClick={() => clickable && onViewAlerts?.(agent.agent_key)}
      className={[
        'text-left rounded-lg border bg-slate-800/50 p-4 transition-all duration-200 card-hover',
        meta.border,
        clickable ? 'hover:bg-slate-800/70 active:scale-[0.99]' : 'cursor-default',
      ].join(' ')}
      title={clickable ? 'View alerts' : undefined}
      aria-label={`${agent.agent_key} ${meta.label}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} aria-hidden />
            <span className="font-mono text-slate-200 text-sm truncate">
              {agent.agent_key}
            </span>
          </div>
          <div className="mt-2">
            <span className={`inline-flex items-center rounded px-2 py-1 text-[11px] font-semibold ${meta.badge}`}>
              {meta.label}
            </span>
            {agent.alert_count > 0 && (
              <span className="ml-2 text-xs text-slate-400">
                {agent.alert_count} alert{agent.alert_count === 1 ? '' : 's'}
              </span>
            )}
          </div>
        </div>
      </div>

      {agent.worst_alert ? (
        <div className="mt-3 space-y-1">
          <p className={`text-sm font-medium ${meta.subtle} truncate`}>
            {agent.worst_alert.title}
          </p>
          <p className="text-xs text-slate-500">
            {formatTimeAgo(agent.worst_alert.timestamp)}
          </p>
        </div>
      ) : (
        <div className="mt-6" />
      )}
    </button>
  );
}

export function AgentHealthGrid() {
  const navigate = useNavigate();
  const { agents, loading, error, refetch } = useAgentHealth();

  const hasAnyUnacked = useMemo(
    () => agents.some((a) => a.alert_count > 0),
    [agents]
  );

  const onViewAlerts = (agentKey: string) => {
    navigate(`/dashboard/alerts?tab=alerts&agent_key=${encodeURIComponent(agentKey)}`);
  };

  if (loading && agents.length === 0) {
    return (
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-slate-300">Agent health</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} i={i} />
          ))}
        </div>
      </div>
    );
  }

  if (error && agents.length === 0) {
    return (
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-slate-300">Agent health</h3>
        <ErrorBanner message={error} onRetry={refetch} />
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <EmptyState title="✅ All agents healthy — no active alerts" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-300">Agent health</h3>
        {error && (
          <span className="text-xs text-rose-400">
            {error}
          </span>
        )}
      </div>

      {!hasAnyUnacked ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <EmptyState title="✅ All agents healthy — no active alerts" />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((a) => (
            <AgentHealthCard key={a.agent_key} agent={a} onViewAlerts={onViewAlerts} />
          ))}
        </div>
      )}
    </div>
  );
}

