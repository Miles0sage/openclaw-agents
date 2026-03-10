import { useCallback, useEffect, useState } from 'react';
import { getAlerts } from '@/api/alerts';
import { USE_MOCKS } from '@/api/constants';
import type { Alert } from '@/types/alerts';

export type AgentState = 'healthy' | 'degraded' | 'open';

export interface AgentHealth {
  agent_key: string;
  state: AgentState;
  alert_count: number;
  worst_alert?: {
    id: string;
    title: string;
    failure_type: string;
    severity: string;
    timestamp: string;
  };
}

function severityRank(severity: string): number {
  if (severity === 'critical') return 3;
  if (severity === 'warning') return 2;
  if (severity === 'info') return 1;
  return 0;
}

function pickWorstAlert(alerts: Alert[]): Alert | undefined {
  if (alerts.length === 0) return undefined;
  const sorted = [...alerts].sort((a, b) => {
    const aCircuit = a.failure_type === 'circuit_open' ? 1 : 0;
    const bCircuit = b.failure_type === 'circuit_open' ? 1 : 0;
    if (aCircuit !== bCircuit) return bCircuit - aCircuit;

    const sr = severityRank(b.severity) - severityRank(a.severity);
    if (sr !== 0) return sr;

    return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
  });
  return sorted[0];
}

function deriveAgentHealth(allAlerts: Alert[]): AgentHealth[] {
  if (allAlerts.length === 0) return [];

  const agentsSeen = new Set<string>();
  for (const a of allAlerts) agentsSeen.add(a.agent_key);

  const unackedByAgent = new Map<string, Alert[]>();
  for (const a of allAlerts) {
    if (a.acknowledged) continue;
    const list = unackedByAgent.get(a.agent_key) ?? [];
    list.push(a);
    unackedByAgent.set(a.agent_key, list);
  }

  const agents: AgentHealth[] = [];
  for (const agent_key of agentsSeen) {
    const unacked = unackedByAgent.get(agent_key) ?? [];
    const worst = pickWorstAlert(unacked);
    const state: AgentState =
      unacked.length === 0 ? 'healthy' : unacked.some((a) => a.failure_type === 'circuit_open') ? 'open' : 'degraded';

    agents.push({
      agent_key,
      state,
      alert_count: unacked.length,
      worst_alert: worst
        ? {
            id: worst.id,
            title: worst.title,
            failure_type: worst.failure_type,
            severity: worst.severity,
            timestamp: worst.timestamp,
          }
        : undefined,
    });
  }

  const stateRank: Record<AgentState, number> = { open: 3, degraded: 2, healthy: 1 };
  agents.sort((a, b) => {
    const sr = stateRank[b.state] - stateRank[a.state];
    if (sr !== 0) return sr;
    const cr = b.alert_count - a.alert_count;
    if (cr !== 0) return cr;
    return a.agent_key.localeCompare(b.agent_key);
  });

  return agents;
}

export function useAgentHealth(): {
  agents: AgentHealth[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
} {
  const [agents, setAgents] = useState<AgentHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setError(null);
    try {
      if (USE_MOCKS) {
        const { mockGetAgentHealth } = await import('@/api/mocks/agentHealth');
        setAgents(mockGetAgentHealth());
        return;
      }

      const data = await getAlerts({ limit: 200 });
      setAgents(deriveAgentHealth(data));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load agent health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
    const id = setInterval(refetch, 30_000);
    return () => clearInterval(id);
  }, [refetch]);

  return { agents, loading, error, refetch };
}

