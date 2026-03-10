export type AlertSeverity = 'critical' | 'warning' | 'info';

export interface Alert {
  id: string;
  timestamp: string;
  severity: AlertSeverity;
  failure_type: string;
  job_id: string;
  agent_key: string;
  title: string;
  message: string;
  diagnostic_steps: string[];
  remediation: string[];
  acknowledged: boolean;
  extra_data: Record<string, unknown>;
}

export interface RunbookEntry {
  failure_type: string;
  severity: AlertSeverity;
  title: string;
  diagnostic_steps: string[];
  remediation: string[];
}
