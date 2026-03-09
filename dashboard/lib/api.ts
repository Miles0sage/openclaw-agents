import "server-only";

import {
  countJobsSince,
  getApiBaseUrl,
  mapPhaseName,
  normalizeStatus,
  PHASE_ORDER,
  phaseLabel,
} from "./format";
import type {
  AgentAnalyticsResponse,
  AnalyticsJobsResponse,
  ChartDatum,
  CostAnalyticsResponse,
  JobCostsResponse,
  JobPhasesResponse,
  JobQueueRow,
  LiveJobResponse,
  MonitoringActiveResponse,
  OverviewMetrics,
  PhaseRow,
  QualityScoreResponse,
  RunnerStatsResponse,
  WorkflowJobsResponse,
} from "./types";

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return fallback;
    }
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

export function fetchRunnerStats() {
  return fetchJson<RunnerStatsResponse>("/api/runner/stats", {
    total_jobs_processed: 0,
    success_rate: 0,
    average_job_duration_seconds: 0,
    jobs_by_status: {},
    jobs_last_24h: 0,
    top_3_failure_reasons: [],
  });
}

export function fetchCostAnalytics() {
  return fetchJson<CostAnalyticsResponse>("/api/analytics/costs", {
    total_cost: 0,
    daily_costs: {},
    weekly_costs: {},
    by_agent: {},
  });
}

export function fetchActiveJobs() {
  return fetchJson<MonitoringActiveResponse>("/api/monitoring/active", {
    active_jobs: 0,
    jobs: {},
  });
}

export function fetchAnalyticsJobs(limit = 50) {
  return fetchJson<AnalyticsJobsResponse>(`/api/analytics/jobs?limit=${limit}`, {
    jobs: [],
    count: 0,
  });
}

export function fetchWorkflowJobs(limit = 50) {
  return fetchJson<WorkflowJobsResponse>(`/api/jobs?limit=${limit}`, {
    jobs: [],
    total: 0,
  });
}

export function fetchJobPhases(jobId: string) {
  return fetchJson<JobPhasesResponse>(`/api/jobs/${jobId}/phases`, {
    job_id: jobId,
    phases: [],
  });
}

export function fetchJobCosts(jobId: string) {
  return fetchJson<JobCostsResponse>(`/api/jobs/${jobId}/costs`, {
    job_id: jobId,
    costs: {
      job_id: jobId,
      total_cost: 0,
      entries_count: 0,
      by_phase: {},
      by_agent: {},
      by_model: {},
      by_tool: {},
    },
    tool_usage: {
      total_calls: 0,
      by_phase: {},
      by_tool: {},
    },
  });
}

export function fetchJobQuality(jobId: string) {
  return fetchJson<QualityScoreResponse>(`/api/analytics/quality/${jobId}`, {
    job_id: jobId,
    score: null,
  });
}

export function fetchAgentAnalytics() {
  return fetchJson<AgentAnalyticsResponse>("/api/analytics/agents", {
    agent_stats: {},
  });
}

export function fetchLiveJob(jobId: string) {
  return fetchJson<LiveJobResponse>(`/api/jobs/${jobId}/live`, {
    job_id: jobId,
  });
}

export function buildQueueRows(
  workflowJobs: WorkflowJobsResponse,
  analyticsJobs: AnalyticsJobsResponse,
): JobQueueRow[] {
  const analyticsById = new Map(analyticsJobs.jobs.map((job) => [job.id, job]));

  return workflowJobs.jobs
    .map((job) => {
      const jobId = job.job_id || job.id || "";
      const analytics = analyticsById.get(jobId);

      return {
        jobId,
        project: job.project || "Unknown project",
        task: job.task || "No task description available",
        status: normalizeStatus(job.status || analytics?.status),
        agent: analytics?.agent || "unknown",
        cost: analytics?.cost || 0,
        createdAt: job.created_at || analytics?.timestamp || "",
        completedAt: job.completed_at || null,
        duration: analytics?.duration || 0,
      };
    })
    .filter((row) => row.jobId)
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt));
}

export function buildOverviewMetrics(
  runnerStats: RunnerStatsResponse,
  costAnalytics: CostAnalyticsResponse,
  activeJobs: MonitoringActiveResponse,
  queueRows: JobQueueRow[],
): OverviewMetrics {
  return {
    todayJobs: runnerStats.jobs_last_24h,
    weekJobs: countJobsSince(queueRows, 7),
    allTimeJobs: runnerStats.total_jobs_processed,
    successRate: runnerStats.success_rate,
    totalCost: costAnalytics.total_cost,
    activeJobs: activeJobs.active_jobs,
    avgDurationSeconds: runnerStats.average_job_duration_seconds,
  };
}

export function buildPhaseRows(
  phasesResponse: JobPhasesResponse,
  liveJob: LiveJobResponse,
): PhaseRow[] {
  const mappedEntries = new Map(
    phasesResponse.phases.map((entry) => [mapPhaseName(entry.phase), entry]),
  );
  const activePhase = mapPhaseName(liveJob.state?.phase);
  const activeIndex = PHASE_ORDER.indexOf((activePhase as (typeof PHASE_ORDER)[number]) || "research");

  return PHASE_ORDER.map((phase, index) => {
    const entry = mappedEntries.get(phase);
    let status: PhaseRow["status"] = "pending";

    if (entry?.completed_at) {
      status = "complete";
    } else if (activePhase) {
      status = activePhase === phase ? "active" : index < activeIndex ? "complete" : "pending";
    } else if (entry?.started_at) {
      status = "active";
    }

    return {
      key: phase,
      label: phaseLabel(phase),
      status,
      startedAt: entry?.started_at || null,
      completedAt: entry?.completed_at || null,
      durationSec: entry?.duration_sec || null,
    };
  });
}

export function buildPhaseCostSeries(payload: JobCostsResponse): ChartDatum[] {
  const direct = payload.costs.by_phase;
  const directHasValues = Object.values(direct).some((value) => value > 0);

  if (directHasValues) {
    return PHASE_ORDER.map((phase) => ({
      label: phaseLabel(phase),
      value: direct[phase] || 0,
    }));
  }

  const toolPhases = payload.tool_usage.by_phase;
  const totalCalls = Object.values(toolPhases).reduce((sum, phase) => sum + (phase.count || 0), 0);

  return PHASE_ORDER.map((phase) => {
    const matchingCount = Object.entries(toolPhases).reduce((sum, [rawPhase, value]) => {
      return sum + (mapPhaseName(rawPhase) === phase ? value.count || 0 : 0);
    }, 0);

    return {
      label: phaseLabel(phase),
      value: totalCalls ? (payload.costs.total_cost * matchingCount) / totalCalls : 0,
    };
  });
}
