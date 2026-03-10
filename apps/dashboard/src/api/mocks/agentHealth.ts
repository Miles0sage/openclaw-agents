import type { AgentHealth } from '@/hooks/useAgentHealth';

export const MOCK_AGENT_HEALTH: AgentHealth[] = [
  {
    agent_key: 'codegen_pro',
    state: 'open',
    alert_count: 1,
    worst_alert: {
      id: 'circuit_open-job-123-20260309T012345',
      title: 'Circuit Breaker Opened',
      failure_type: 'circuit_open',
      severity: 'critical',
      timestamp: new Date(Date.now() - 120000).toISOString(),
    },
  },
  {
    agent_key: 'pentest_ai',
    state: 'degraded',
    alert_count: 2,
    worst_alert: {
      id: 'stuck_looper-job-456-20260309T013000',
      title: 'Agent Stuck in Loop',
      failure_type: 'stuck_looper',
      severity: 'warning',
      timestamp: new Date(Date.now() - 300000).toISOString(),
    },
  },
  {
    agent_key: 'overseer',
    state: 'healthy',
    alert_count: 0,
  },
  {
    agent_key: 'supabase_connector',
    state: 'healthy',
    alert_count: 0,
  },
];

export function mockGetAgentHealth(): AgentHealth[] {
  return [...MOCK_AGENT_HEALTH];
}
