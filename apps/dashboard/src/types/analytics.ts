// Judge / quality
export interface JudgeSummaryByAgent {
  agent_key: string;
  avg_score: number;
  count: number;
}

export interface JudgeSummary {
  period_days: number;
  aggregate_score: number;
  by_agent: JudgeSummaryByAgent[];
  pass_count: number;
  fail_count: number;
  dimensions: Record<string, number>;
}

// Traces
export interface TraceListItem {
  trace_id: string;
  job_id: string;
  name: string;
  start_time: string;
  duration_ms: number;
  attributes?: Record<string, string>;
  /** From traces/recent: ok | error | completed | failed */
  status?: string;
}

export interface TracesResponse {
  traces: TraceListItem[];
}

export interface Span {
  trace_id?: string;
  span_id: string;
  parent_span_id?: string;
  name: string;
  start_time: string;
  duration_ms: number;
  attributes?: Record<string, string>;
  children?: Span[];
}

export interface TraceDetail {
  trace_id: string;
  job_id: string;
  spans: Span[];
}

// SSE live stream
export type LivePhase = 'RESEARCH' | 'PLAN' | 'EXECUTE' | 'VERIFY' | 'DELIVER';

export interface PhaseEvent {
  phase: LivePhase;
  progress_pct: number;
}

export interface ToolCallEvent {
  tool: string;
  input_preview: string;
  result_ok: boolean;
}

export interface CostEvent {
  accumulated_usd: number;
}

export interface DoneEvent {
  success: boolean;
  final_cost_usd: number;
}

// Knowledge graph
export interface KgToolNode {
  key: string;
  usage_count: number;
}

export interface KgEdge {
  source: string;
  target: string;
  strength: number;
}

export interface KgAgentStats {
  agent_key: string;
  success_rate: number;
  avg_cost_usd: number;
  favorite_tools: string[];
}

export interface KgSummary {
  tools: KgToolNode[];
  edges: KgEdge[];
  agents: KgAgentStats[];
}

export interface KgRecommendationRow {
  agent_key: string;
  recommended_chain: string[];
  score?: number;
}

export interface KgRecommendResponse {
  agent_key: string;
  recommendations: KgRecommendationRow[];
}

// Agents (for /api/analytics/agents)
export interface AgentStats {
  agent_key: string;
  success_rate: number;
  avg_cost_usd: number;
  total_jobs: number;
  favorite_tools: string[];
}

export interface AgentsResponse {
  agents: AgentStats[];
}
