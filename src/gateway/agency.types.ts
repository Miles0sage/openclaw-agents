/**
 * Agency HTTP Types
 * TypeScript interfaces for the 24/7 agentic agency system
 */

export interface ProjectConfig {
  id: string;
  name: string;
  repo: string;
  local_path: string;
  github_url: string;
  branch: string;
  language: string;
  test_command: string;
  build_command?: string | null;
  deploy_url?: string | null;
  deploy_command?: string | null;
  sensitive_files?: string[];
  auth_files?: string[];
  payment_files?: string[];
  database_files?: string[];
  queue_files?: string[];
  routing_files?: string[];
  description?: string;
}

export interface AgencyConfig {
  projects: ProjectConfig[];
  agency: {
    name: string;
    owner: string;
    timezone: string;
    slack_webhook?: string;
    github_token?: string;
    anthropic_api_key?: string;
    vercel_token?: string;
  };
  cycle: {
    frequency: string;
    cron: string;
    max_parallel_agents: number;
    timeout_minutes: number;
  };
  costs: {
    per_cycle_hard_cap: number;
    per_cycle_typical: number;
    per_project_cap: number;
    daily_hard_cap: number;
    monthly_hard_cap: number;
    monthly_soft_cap: number;
  };
  model_selection: {
    planning: string;
    execution: string;
    review: string;
  };
}

export interface ProjectStatus {
  status: "planning" | "planning_done" | "executing" | "merged" | "failed" | "review";
  plan_generated?: string;
  plan_file?: string;
  pr_url?: string | null;
  pr_title?: string;
  tests_passed?: boolean | null;
  auto_merged?: boolean | null;
  error_log?: string | null;
  test_status?: "pending" | "running" | "passed" | "failed";
}

export interface Cycle {
  cycle_id: string;
  status: "planning" | "execution" | "review" | "completed" | "failed";
  phase: "planning" | "execution" | "review";
  created_at: string;
  started_at: string;
  completed_at?: string | null;
  projects: Record<string, ProjectStatus>;
  costs: {
    planning: number;
    execution: number;
    review: number;
    total: number;
  };
}

export interface CostEntry {
  cycle_id: string;
  project_id: string;
  phase: "planning" | "execution" | "review";
  model: string;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  timestamp: string;
}

// Response types
export interface TriggerResponse {
  cycle_id: string;
  status: string;
  projects_queued: number;
  estimated_cost: string;
  estimated_time_minutes: number;
  timestamp: string;
  job_urls: {
    planning_queue: string;
    tracking_url: string;
  };
}

export interface StatusResponse {
  cycle_id: string;
  status: string;
  phase: string;
  progress: {
    planning: { completed: number; total: number; status: string };
    execution: { completed: number; total: number; status: string };
    review: { completed: number; total: number; status: string };
  };
  projects: Record<string, ProjectStatus & { deployment?: string }>;
  costs_so_far?: {
    planning: string;
    execution: string;
    total: string;
  };
  costs?: {
    planning: string;
    execution: string;
    review: string;
    total: string;
  };
  eta_completion?: string;
  results?: {
    total_prs: number;
    auto_merged: number;
    opus_reviewed: number;
    rejected: number;
    success_rate: string;
  };
  updated_at: string;
  completed_at?: string;
  slack_notification_sent?: boolean;
}

export interface CostsResponse {
  period: string;
  cycles_completed: number;
  cycles_in_progress: number;
  costs: {
    total: string;
    by_phase: {
      planning: {
        total: string;
        cycles: number;
        avg_per_cycle: string;
        model: string;
        tokens_used: number;
      };
      execution: {
        total: string;
        cycles: number;
        avg_per_cycle: string;
        model: string;
        tokens_used: number;
      };
      review: {
        total: string;
        cycles: number;
        avg_per_cycle: string;
        model: string;
        tokens_used: number;
      };
    };
    by_project: Record<string, string>;
  };
  guardrails: {
    per_cycle_cap: string;
    per_cycle_max_exceeded: number;
    daily_cap: string;
    daily_max_exceeded: number;
    monthly_cap: string;
    remaining_budget: string;
  };
  projections: {
    projected_monthly_total: string;
    days_remaining_in_month: number;
    will_exceed_budget: boolean;
  };
  efficiency: {
    cost_per_feature: string;
    prs_merged: number;
    avg_pr_size: string;
    test_pass_rate: string;
  };
  timestamp: string;
}

export interface ConfigResponse {
  status: string;
  timestamp: string;
  changes_applied: Record<string, unknown>;
  config_file_updated: string;
  next_cycle: string;
  slack_notification_sent: boolean;
  note: string;
}

export interface ErrorResponse {
  error: string;
  code: string;
  hint?: string;
  reason?: string;
  valid_projects?: string[];
  current_cycle_id?: string;
}
