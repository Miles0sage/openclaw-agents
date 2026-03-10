/**
 * Monitoring System Type Definitions
 * Interfaces for dashboard state, alerts, metrics, and events
 */

export interface AgentStatus {
  name: string;
  status: "online" | "offline" | "idle" | "processing";
  uptime_seconds: number;
  last_activity: string; // ISO timestamp
  task_count: number;
  success_count: number;
  error_count: number;
}

export interface CostSummary {
  today: number;
  this_week: number;
  this_month: number;
  by_project: Record<string, number>;
  by_model: Record<string, number>;
  daily_rate: number; // average cost per day
  projected_monthly: number;
  currency: "USD";
}

export interface Alert {
  id: string;
  type: "error" | "warning" | "success" | "info";
  timestamp: string; // ISO timestamp
  message: string;
  context?: Record<string, unknown>;
  acknowledged: boolean;
  acknowledged_at?: string;
  source: "system" | "agent" | "task" | "cost";
}

export interface TaskMetric {
  task_id: string;
  agent_id: string;
  project_id: string;
  timestamp: string;
  response_time_seconds: number;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  test_pass_rate: number; // 0-100
  accuracy_score: number; // 0-100
  status: "pending" | "in_progress" | "completed" | "failed";
}

export interface AggregatedMetrics {
  period: "day" | "week" | "month";
  start_date: string;
  end_date: string;
  total_tasks: number;
  avg_response_time_seconds: number;
  total_tokens_input: number;
  total_tokens_output: number;
  total_cost_usd: number;
  avg_test_pass_rate: number;
  avg_accuracy_score: number;
  success_rate: number; // 0-100
  by_agent: Record<string, { task_count: number; avg_response_time: number; success_rate: number }>;
  by_project: Record<string, { task_count: number; total_cost: number }>;
}

export interface Event {
  timestamp: string; // ISO timestamp
  type: string; // e.g., "task_started", "task_completed", "error", "cost_alert"
  agent_id?: string;
  task_id?: string;
  project_id?: string;
  level: "debug" | "info" | "warn" | "error";
  message: string;
  data?: Record<string, unknown>;
}

export interface DashboardState {
  timestamp: string;
  agents: AgentStatus[];
  costs: CostSummary;
  alerts: Alert[];
  recent_events: Event[];
  metrics: {
    today: AggregatedMetrics;
    this_week: AggregatedMetrics;
    this_month: AggregatedMetrics;
  };
  system_health: {
    memory_usage_percent: number;
    uptime_hours: number;
    active_tasks: number;
    pending_tasks: number;
  };
}

export interface ProjectStats {
  project_id: string;
  total_tasks: number;
  total_cost: number;
  avg_response_time: number;
  success_rate: number;
  by_agent: Record<string, { task_count: number; cost: number }>;
}
