export interface RunnerStatsResponse {
  total_jobs_processed: number;
  success_rate: number;
  average_job_duration_seconds: number;
  jobs_by_status: Record<string, number>;
  jobs_last_24h: number;
  top_3_failure_reasons: Array<[string, number]> | Array<{ reason: string; count: number }>;
}

export interface CostAnalyticsResponse {
  total_cost: number;
  daily_costs: Record<string, number>;
  weekly_costs: Record<string, number>;
  by_agent: Record<string, number>;
  timestamp?: string;
  error?: string;
}

export interface MonitoringJobState {
  job_id?: string;
  phase?: string;
  progress_pct?: number;
  active_tools?: string[];
  tokens_used?: number;
  cost_usd?: number;
  last_event?: string;
  created_at?: string;
  status?: string;
}

export interface MonitoringActiveResponse {
  active_jobs: number;
  jobs: Record<string, MonitoringJobState>;
}

export interface AnalyticsJobRecord {
  id: string;
  agent: string;
  status: string;
  duration: number;
  cost: number;
  timestamp: string;
  event_type: string;
}

export interface AnalyticsJobsResponse {
  jobs: AnalyticsJobRecord[];
  count: number;
  timestamp?: string;
  error?: string;
}

export interface WorkflowJobRecord {
  id?: string;
  job_id?: string;
  project?: string;
  task?: string;
  status?: string;
  created_at?: string;
  completed_at?: string | null;
  branch_name?: string | null;
  pr_url?: string | null;
}

export interface WorkflowJobsResponse {
  jobs: WorkflowJobRecord[];
  total: number;
  error?: string;
}

export interface PhaseEntry {
  phase: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_sec?: number | null;
}

export interface JobPhasesResponse {
  job_id: string;
  phases: PhaseEntry[];
}

export interface JobCostBreakdown {
  job_id: string;
  total_cost: number;
  entries_count: number;
  by_phase: Record<string, number>;
  by_agent: Record<string, number>;
  by_model: Record<string, number>;
  by_tool: Record<
    string,
    {
      count: number;
      total_cost: number;
      avg_elapsed_s: number;
    }
  >;
}

export interface ToolUsageBreakdown {
  total_calls: number;
  by_phase: Record<string, { count: number; tools: string[] }>;
  by_tool: Record<
    string,
    {
      count: number;
      avg_elapsed_s: number;
      by_status?: Record<string, number>;
      by_risk_level?: Record<string, number>;
    }
  >;
}

export interface JobCostsResponse {
  job_id: string;
  costs: JobCostBreakdown;
  tool_usage: ToolUsageBreakdown;
}

export interface QualityDimension {
  dimension: string;
  score: number;
  reasoning: string;
  weight: number;
}

export interface QualityScoreResponse {
  job_id: string;
  score?: number | null;
  overall_score?: number | null;
  confidence?: number;
  dimensions?: QualityDimension[];
  message?: string;
  error?: string;
}

export interface AgentStats {
  jobs: number;
  success: number;
  failed: number;
  total_cost: number;
  total_duration: number;
  success_rate: number;
  avg_duration: number;
  avg_cost: number;
}

export interface AgentAnalyticsResponse {
  agent_stats: Record<string, AgentStats>;
  timestamp?: string;
  error?: string;
}

export interface LiveJobResponse {
  job_id: string;
  state?: MonitoringJobState;
  error?: string;
}

export interface JobQueueRow {
  jobId: string;
  project: string;
  task: string;
  status: string;
  agent: string;
  cost: number;
  createdAt: string;
  completedAt: string | null;
  duration: number;
}

export interface OverviewMetrics {
  todayJobs: number;
  weekJobs: number;
  allTimeJobs: number;
  successRate: number;
  totalCost: number;
  activeJobs: number;
  avgDurationSeconds: number;
}

export interface PhaseRow {
  key: string;
  label: string;
  status: "complete" | "active" | "pending";
  startedAt?: string | null;
  completedAt?: string | null;
  durationSec?: number | null;
}

export interface ChartDatum {
  label: string;
  value: number;
}
