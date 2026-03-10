import type {
  JudgeSummary,
  TraceDetail,
  TracesResponse,
  KgSummary,
  KgRecommendResponse,
  AgentsResponse,
} from '@/types/analytics';
import type { HealthResponse } from '../analytics';

export function mockJudgeSummary(_days: number): JudgeSummary {
  return {
    period_days: 7,
    aggregate_score: 0.72,
    by_agent: [
      { agent_key: 'coder_agent', avg_score: 0.78, count: 42 },
      { agent_key: 'researcher_agent', avg_score: 0.68, count: 28 },
      { agent_key: 'writer_agent', avg_score: 0.71, count: 15 },
    ],
    pass_count: 31,
    fail_count: 11,
    dimensions: { correctness: 0.8, completeness: 0.7, security: 0.65, clarity: 0.72, relevance: 0.75 },
  };
}

export function mockJudge(_jobId: string): Promise<{ score: number; dimensions?: Record<string, number> }> {
  return Promise.resolve({
    score: 0.78,
    dimensions: { correctness: 0.85, completeness: 0.7, security: 0.8 },
  });
}

export function mockTraces(limit: number): TracesResponse {
  const traces = Array.from({ length: Math.min(limit, 10) }, (_, i) => ({
    trace_id: `trace-${i + 1}`,
    job_id: `job-${i + 1}`,
    name: 'main',
    start_time: new Date(Date.now() - (i + 1) * 3600000).toISOString(),
    duration_ms: 12000 + i * 3000,
    attributes: { agent: 'coder_agent', phase: 'EXECUTE' },
  }));
  return { traces };
}

export function mockTracesRecent(limit: number): TracesResponse {
  const traces = Array.from({ length: Math.min(limit, 20) }, (_, i) => ({
    trace_id: `trace-${i + 1}`,
    job_id: `job-${i + 1}`,
    name: 'main',
    start_time: new Date(Date.now() - (i + 1) * 60000).toISOString(),
    duration_ms: 5000 + i * 2000,
    attributes: { agent: 'coder_agent', phase: 'EXECUTE' },
    status: i % 4 === 0 ? 'error' : 'ok',
  }));
  return { traces };
}

export function mockTrace(jobId: string): TraceDetail {
  const base = jobId.startsWith('job-') ? Number(jobId.replace('job-', '')) : 1;
  const t0 = new Date(Date.now() - 60000).toISOString();
  const t1 = new Date(Date.now() - 55000).toISOString();
  const t2 = new Date(Date.now() - 52000).toISOString();
  const t3 = new Date(Date.now() - 51000).toISOString();
  const t4 = new Date(Date.now() - 48000).toISOString();
  return {
    trace_id: `trace-${base}`,
    job_id: jobId,
    spans: [
      { span_id: '1', name: 'job', start_time: t0, duration_ms: 45000, attributes: { agent: 'coder_agent' } },
      { span_id: '2', parent_span_id: '1', name: 'RESEARCH', start_time: t0, duration_ms: 5000 },
      { span_id: '3', parent_span_id: '1', name: 'PLAN', start_time: t1, duration_ms: 3000 },
      { span_id: '4', parent_span_id: '1', name: 'EXECUTE', start_time: t2, duration_ms: 35000 },
      { span_id: '5', parent_span_id: '4', name: 'tool: read_file', start_time: t3, duration_ms: 200, attributes: { tool: 'read_file' } },
      { span_id: '6', parent_span_id: '4', name: 'tool: run_terminal_cmd', start_time: t4, duration_ms: 5000, attributes: { tool: 'run_terminal_cmd' } },
    ],
  };
}

export function mockKgSummary(): KgSummary {
  return {
    tools: [
      { key: 'read_file', usage_count: 120 },
      { key: 'write', usage_count: 95 },
      { key: 'run_terminal_cmd', usage_count: 88 },
      { key: 'grep', usage_count: 70 },
      { key: 'web_search', usage_count: 45 },
    ],
    edges: [
      { source: 'read_file', target: 'write', strength: 0.9 },
      { source: 'read_file', target: 'grep', strength: 0.7 },
      { source: 'run_terminal_cmd', target: 'read_file', strength: 0.6 },
      { source: 'web_search', target: 'write', strength: 0.5 },
    ],
    agents: [
      { agent_key: 'coder_agent', success_rate: 0.85, avg_cost_usd: 0.02, favorite_tools: ['read_file', 'write', 'run_terminal_cmd'] },
      { agent_key: 'researcher_agent', success_rate: 0.78, avg_cost_usd: 0.03, favorite_tools: ['web_search', 'read_file'] },
    ],
  };
}

export function mockKgRecommend(agentKey: string): KgRecommendResponse {
  return {
    agent_key: agentKey,
    recommendations: [
      { agent_key: agentKey, recommended_chain: ['read_file', 'grep', 'write'], score: 0.92 },
      { agent_key: agentKey, recommended_chain: ['web_search', 'read_file', 'write'], score: 0.88 },
    ],
  };
}

export function mockDag(_workflowId: string): Promise<unknown> {
  return Promise.resolve({ nodes: [], edges: [] });
}

export function mockHealth(): HealthResponse {
  return {
    status: 'healthy',
    uptime_seconds: 86400,
    total_tools: 85,
    python_version: '3.11.0',
    version: '1.0.0',
    memory_usage: 0.42,
    memory_mb: 256,
    timestamp: new Date().toISOString(),
  };
}

export function mockAgents(): AgentsResponse {
  return {
    agents: [
      { agent_key: 'coder_agent', success_rate: 0.85, avg_cost_usd: 0.02, total_jobs: 42, favorite_tools: ['read_file', 'write', 'run_terminal_cmd'] },
      { agent_key: 'researcher_agent', success_rate: 0.78, avg_cost_usd: 0.03, total_jobs: 28, favorite_tools: ['web_search', 'read_file'] },
      { agent_key: 'writer_agent', success_rate: 0.71, avg_cost_usd: 0.025, total_jobs: 15, favorite_tools: ['read_file', 'write'] },
    ],
  };
}
