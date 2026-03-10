import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { AlertSeverity } from '@/types/alerts';
import { useAlerts } from '@/hooks/useAlerts';
import { AlertDetail } from './AlertDetail';

const severityLabel: Record<AlertSeverity, string> = {
  critical: 'CRITICAL',
  warning: 'WARNING',
  info: 'INFO',
};

const severityBg: Record<AlertSeverity, string> = {
  critical: 'bg-rose-500/20 border-rose-500/40',
  warning: 'bg-amber-500/20 border-amber-500/40',
  info: 'bg-sky-500/20 border-sky-500/40',
};

const severityDot: Record<AlertSeverity, string> = {
  critical: 'bg-rose-500',
  warning: 'bg-amber-500',
  info: 'bg-sky-500',
};

function formatTimeAgo(iso: string): string {
  const d = new Date(iso);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}min ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

export function AlertsPanel() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [jobIdFilter, setJobIdFilter] = useState('');
  const [agentKeyFilter, setAgentKeyFilter] = useState(() => searchParams.get('agent_key') ?? '');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const agentKeyFromUrl = useMemo(() => searchParams.get('agent_key') ?? '', [searchParams]);

  useEffect(() => {
    if (agentKeyFromUrl !== agentKeyFilter) setAgentKeyFilter(agentKeyFromUrl);
    // We intentionally don't include agentKeyFilter in deps; URL is source of truth for navigation
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentKeyFromUrl]);

  const params =
    severityFilter === 'all'
      ? { limit: 200 }
      : { limit: 200, severity: severityFilter };
  const { alerts, loading, error, refetch, acknowledge } = useAlerts(params);

  const filteredAlerts = useMemo(() => {
    const jobNeedle = jobIdFilter.trim().toLowerCase();
    const agentNeedle = agentKeyFilter.trim().toLowerCase();
    return alerts.filter((a) => {
      if (jobNeedle && !a.job_id.toLowerCase().includes(jobNeedle)) return false;
      if (agentNeedle && !a.agent_key.toLowerCase().includes(agentNeedle)) return false;
      return true;
    });
  }, [alerts, jobIdFilter, agentKeyFilter]);

  const setAgentKeyFilterAndUrl = (next: string) => {
    setAgentKeyFilter(next);
    const nextParams = new URLSearchParams(searchParams);
    const trimmed = next.trim();
    if (trimmed) nextParams.set('agent_key', trimmed);
    else nextParams.delete('agent_key');
    setSearchParams(nextParams, { replace: true });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-sm px-2 py-1.5"
        >
          <option value="all">All</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
        <input
          type="text"
          value={jobIdFilter}
          onChange={(e) => setJobIdFilter(e.target.value)}
          placeholder="Job ID"
          className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-sm px-2 py-1.5 w-32 placeholder-slate-500"
        />
        <input
          type="text"
          value={agentKeyFilter}
          onChange={(e) => setAgentKeyFilterAndUrl(e.target.value)}
          placeholder="Agent key"
          className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-sm px-2 py-1.5 w-32 placeholder-slate-500"
        />
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600"
        >
          Refresh
        </button>
      </div>

      {error && (
        <p className="text-rose-400 text-sm">{error}</p>
      )}
      {loading && filteredAlerts.length === 0 && (
        <p className="text-slate-400 text-sm">Loading alerts…</p>
      )}
      {!loading && filteredAlerts.length === 0 && (
        <p className="text-slate-500 text-sm">No alerts</p>
      )}

      <ul className="space-y-2">
        {filteredAlerts.map((alert) => (
          <li
            key={alert.id}
            className={`rounded border p-3 ${severityBg[alert.severity]} ${alert.acknowledged ? 'opacity-60' : ''}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`h-2 w-2 rounded-full shrink-0 ${severityDot[alert.severity]}`} aria-hidden />
                  <span className={`font-medium text-slate-200 ${alert.acknowledged ? 'line-through' : ''}`}>
                    {severityLabel[alert.severity]} {alert.title}
                  </span>
                  <span className="text-slate-500 text-sm">{alert.job_id}</span>
                  <span className="text-slate-500 text-sm">{formatTimeAgo(alert.timestamp)}</span>
                </div>
                <p className="text-slate-400 text-sm mt-1 truncate">{alert.agent_key} — {alert.message}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setExpandedId(expandedId === alert.id ? null : alert.id)}
                  className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-600"
                >
                  {expandedId === alert.id ? 'Hide' : 'View Details'}
                </button>
                {!alert.acknowledged && (
                  <button
                    type="button"
                    onClick={() => acknowledge(alert.id)}
                    className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-600"
                  >
                    Acknowledge
                  </button>
                )}
                {alert.acknowledged && (
                  <span className="text-slate-500 text-xs">✓ Acknowledged</span>
                )}
              </div>
            </div>
            {expandedId === alert.id && <AlertDetail alert={alert} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
