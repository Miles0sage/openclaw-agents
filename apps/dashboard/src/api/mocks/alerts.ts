import type { Alert, RunbookEntry } from '@/types/alerts';
import type { AlertsParams } from '../alerts';

const MOCK_ALERTS: Alert[] = [
  {
    id: 'circuit_open-job-123-20260309T012345',
    timestamp: new Date(Date.now() - 120000).toISOString(),
    severity: 'critical',
    failure_type: 'circuit_open',
    job_id: 'job-123',
    agent_key: 'codegen_pro',
    title: 'Circuit Breaker Opened',
    message: 'Circuit opened for codegen_pro after 5 consecutive failures',
    diagnostic_steps: [
      'Check which agent/provider triggered the breaker',
      'Inspect error logs for root cause',
      'Check provider status page',
      'Check if API key is valid and has credits',
    ],
    remediation: [
      'Wait for half-open recovery (automatic)',
      'If auth issue: check and rotate API key',
      'If rate limit: reduce concurrency or wait',
      'If provider down: switch to fallback provider',
    ],
    acknowledged: false,
    extra_data: {},
  },
  {
    id: 'stuck_looper-job-456-20260309T013000',
    timestamp: new Date(Date.now() - 300000).toISOString(),
    severity: 'warning',
    failure_type: 'stuck_looper',
    job_id: 'job-456',
    agent_key: 'codegen_elite',
    title: 'Agent Stuck in Loop',
    message: 'Stuck after 2 corrections on file_read loop',
    diagnostic_steps: ['Check last 10 tool calls for repetition'],
    remediation: ['Inject corrective guidance to change strategy'],
    acknowledged: false,
    extra_data: {},
  },
  {
    id: 'info-job-789',
    timestamp: new Date(Date.now() - 60000).toISOString(),
    severity: 'info',
    failure_type: 'context_compact',
    job_id: 'job-789',
    agent_key: 'coder_agent',
    title: 'Context compacted',
    message: 'Session context was compacted to stay within budget',
    diagnostic_steps: [],
    remediation: [],
    acknowledged: true,
    extra_data: {},
  },
];

const MOCK_RUNBOOK: RunbookEntry[] = [
  { failure_type: 'circuit_open', severity: 'critical', title: 'Circuit Breaker Opened', diagnostic_steps: ['Check which agent triggered the breaker', 'Inspect error logs'], remediation: ['Wait for half-open recovery', 'Rotate API key if auth issue'] },
  { failure_type: 'stuck_looper', severity: 'warning', title: 'Agent Stuck in Loop', diagnostic_steps: ['Check last 10 tool calls'], remediation: ['Inject corrective guidance'] },
  { failure_type: 'rate_limit', severity: 'warning', title: 'Rate Limit Hit', diagnostic_steps: ['Check provider limits'], remediation: ['Back off and retry', 'Reduce concurrency'] },
  { failure_type: 'context_overflow', severity: 'warning', title: 'Context Overflow', diagnostic_steps: ['Check token usage'], remediation: ['Compact or summarize context'] },
  { failure_type: 'budget_exceeded', severity: 'critical', title: 'Budget Exceeded', diagnostic_steps: ['Check job cost'], remediation: ['Increase budget or simplify task'] },
  { failure_type: 'credit_exhausted', severity: 'critical', title: 'Credit Exhausted', diagnostic_steps: ['Check account credits'], remediation: ['Top up credits'] },
  { failure_type: 'guardrail_violation', severity: 'warning', title: 'Guardrail Violation', diagnostic_steps: ['Review kill reason'], remediation: ['Adjust guardrails or task'] },
  { failure_type: 'timeout', severity: 'warning', title: 'Operation Timeout', diagnostic_steps: ['Check slow steps'], remediation: ['Increase timeout or optimize'] },
];

const acknowledgedIds = new Set<string>();

export function mockGetAlerts(params: AlertsParams): Alert[] {
  let list = MOCK_ALERTS.map((a) => (acknowledgedIds.has(a.id) ? { ...a, acknowledged: true } : a));
  if (params.severity) list = list.filter((a) => a.severity === params.severity);
  if (params.job_id) list = list.filter((a) => a.job_id.includes(params.job_id!));
  const limit = params.limit ?? 50;
  return list.slice(0, limit);
}

export function mockAcknowledgeAlert(alertId: string): void {
  acknowledgedIds.add(alertId);
}

export function mockGetRunbook(): RunbookEntry[] {
  return [...MOCK_RUNBOOK];
}

export function mockGetRunbookEntry(failureType: string): RunbookEntry | null {
  return MOCK_RUNBOOK.find((e) => e.failure_type === failureType) ?? null;
}
