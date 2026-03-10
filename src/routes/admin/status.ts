/**
 * Admin Status Dashboard Route
 * Consolidated admin endpoint providing system health, cost tracking,
 * agent performance, and channel statistics for the OpenClaw gateway.
 *
 * Routes:
 *   GET /admin/status — Full system status snapshot (JSON)
 *   GET /admin/logs   — Filtered event log entries (JSON)
 */

import type { Request, Response } from "express";
import { Router } from "express";
import type { AggregatedMetrics, AgentStatus, CostSummary, Event } from "../../monitoring/types.js";
import { alertManager } from "../../monitoring/alerts.js";
import { dashboard } from "../../monitoring/dashboard.js";
import { eventLogger } from "../../monitoring/event-logger.js";
import { metricsCollector } from "../../monitoring/metrics.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentBreakdown {
  agent_id: string;
  calls: number;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  avg_response_time: number;
  success_rate: number;
}

interface ChannelBreakdown {
  channel: string;
  messages: number;
  avg_latency_seconds: number;
  error_rate: number;
}

interface PerformanceMetrics {
  p95_latency_seconds: number;
  avg_latency_seconds: number;
  error_rate: number;
  total_requests: number;
  success_count: number;
  error_count: number;
}

interface HealthStatus {
  status: "healthy" | "degraded" | "critical";
  reasons: string[];
}

interface AdminStatusResponse {
  success: boolean;
  timestamp: string;
  uptime_seconds: number;
  uptime_human: string;
  health: HealthStatus;
  costs: {
    today_usd: number;
    this_month_usd: number;
    projected_30d_usd: number;
    daily_rate_usd: number;
    by_project: Record<string, number>;
    by_model: Record<string, number>;
    currency: string;
  };
  performance: PerformanceMetrics;
  agents: AgentBreakdown[];
  channels: ChannelBreakdown[];
  system: {
    memory_usage_percent: number;
    active_tasks: number;
    pending_tasks: number;
  };
  alerts_active: number;
}

interface AdminLogsResponse {
  success: boolean;
  timestamp: string;
  total: number;
  offset: number;
  limit: number;
  entries: Event[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PROCESS_START = Date.now();

function uptimeSeconds(): number {
  return Math.floor((Date.now() - PROCESS_START) / 1000);
}

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const parts: string[] = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  if (m > 0) parts.push(`${m}m`);
  parts.push(`${s}s`);
  return parts.join(" ");
}

/** Estimate p95 latency from a sorted array of response times. */
function estimateP95(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(Math.ceil(sorted.length * 0.95) - 1, sorted.length - 1);
  return Math.round((sorted[idx] ?? 0) * 100) / 100;
}

function buildAgentBreakdowns(
  dayMetrics: AggregatedMetrics,
  monthMetrics: AggregatedMetrics,
): AgentBreakdown[] {
  const agents: AgentBreakdown[] = [];
  const byAgent = dayMetrics.by_agent ?? {};

  for (const [agentId, info] of Object.entries(byAgent)) {
    const monthInfo = monthMetrics.by_agent?.[agentId];
    agents.push({
      agent_id: agentId,
      calls: info.task_count,
      tokens_input: 0, // Not tracked per-agent in aggregated metrics
      tokens_output: 0,
      cost_usd: 0,
      avg_response_time: info.avg_response_time,
      success_rate: info.success_rate,
    });
  }

  // If day metrics are empty, fall back to month data
  if (agents.length === 0) {
    for (const [agentId, info] of Object.entries(monthMetrics.by_agent ?? {})) {
      agents.push({
        agent_id: agentId,
        calls: info.task_count,
        tokens_input: 0,
        tokens_output: 0,
        cost_usd: 0,
        avg_response_time: info.avg_response_time,
        success_rate: info.success_rate,
      });
    }
  }

  return agents;
}

function buildChannelBreakdowns(agentStatuses: AgentStatus[]): ChannelBreakdown[] {
  // Derive channel-level stats from agent statuses.
  // Each agent is treated as a logical channel for this breakdown.
  const channels: ChannelBreakdown[] = [];

  for (const agent of agentStatuses) {
    const total = agent.success_count + agent.error_count;
    const errorRate = total > 0 ? (agent.error_count / total) * 100 : 0;

    channels.push({
      channel: agent.name,
      messages: agent.task_count,
      avg_latency_seconds: 0, // Not directly available per-channel
      error_rate: Math.round(errorRate * 100) / 100,
    });
  }

  return channels;
}

function determineHealth(errorRate: number, agentStatuses: AgentStatus[]): HealthStatus {
  const reasons: string[] = [];
  let status: HealthStatus["status"] = "healthy";

  // Error rate thresholds
  if (errorRate > 25) {
    status = "critical";
    reasons.push(`Error rate is ${errorRate.toFixed(1)}% (threshold: 25%)`);
  } else if (errorRate > 10) {
    status = "degraded";
    reasons.push(`Error rate is ${errorRate.toFixed(1)}% (threshold: 10%)`);
  }

  // Check for offline agents
  const offlineAgents = agentStatuses.filter((a) => a.status === "offline");
  if (offlineAgents.length > 0) {
    if (status === "healthy") status = "degraded";
    reasons.push(
      `${offlineAgents.length} agent(s) offline: ${offlineAgents.map((a) => a.name).join(", ")}`,
    );
  }

  // Memory pressure
  const mem = process.memoryUsage();
  const memPercent = Math.round((mem.heapUsed / mem.heapTotal) * 100);
  if (memPercent > 90) {
    if (status !== "critical") status = "degraded";
    reasons.push(`High memory usage: ${memPercent}%`);
  }

  if (reasons.length === 0) {
    reasons.push("All systems operational");
  }

  return { status, reasons };
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

const router = Router();

/**
 * GET /admin/status
 * Returns a comprehensive JSON snapshot of the system's operational state.
 */
router.get("/admin/status", async (_req: Request, res: Response): Promise<void> => {
  try {
    // Gather data from monitoring subsystems in parallel
    const [dashboardState, dayMetrics, monthMetrics, agentStatuses, costSummary] =
      await Promise.all([
        dashboard.getDashboardState(),
        metricsCollector.getStats("day"),
        metricsCollector.getStats("month"),
        dashboard.getAgentStatus(),
        dashboard.getCostSummary(),
      ]);

    // Performance metrics
    const totalRequests = dayMetrics.total_tasks;
    const successCount = Math.round((dayMetrics.success_rate / 100) * totalRequests);
    const errorCount = totalRequests - successCount;
    const errorRate =
      totalRequests > 0 ? Math.round((errorCount / totalRequests) * 100 * 100) / 100 : 0;

    // We don't have raw latency values, so approximate p95 from avg
    const p95Approx = Math.round(dayMetrics.avg_response_time_seconds * 1.6 * 100) / 100;

    const performance: PerformanceMetrics = {
      p95_latency_seconds: p95Approx,
      avg_latency_seconds: dayMetrics.avg_response_time_seconds,
      error_rate: errorRate,
      total_requests: totalRequests,
      success_count: successCount,
      error_count: errorCount,
    };

    // Cost breakdown
    const daysElapsedInMonth = Math.max(new Date().getDate(), 1);
    const dailyRate = daysElapsedInMonth > 0 ? monthMetrics.total_cost_usd / daysElapsedInMonth : 0;
    const projected30d = Math.round(dailyRate * 30 * 100) / 100;

    const costs = {
      today_usd: Math.round(dayMetrics.total_cost_usd * 10000) / 10000,
      this_month_usd: Math.round(monthMetrics.total_cost_usd * 10000) / 10000,
      projected_30d_usd: projected30d,
      daily_rate_usd: Math.round(dailyRate * 10000) / 10000,
      by_project: costSummary.by_project,
      by_model: costSummary.by_model,
      currency: costSummary.currency,
    };

    // Agent and channel breakdowns
    const agents = buildAgentBreakdowns(dayMetrics, monthMetrics);
    const channels = buildChannelBreakdowns(agentStatuses);

    // Health determination
    const health = determineHealth(errorRate, agentStatuses);

    // System metrics
    const mem = process.memoryUsage();
    const memPercent = Math.round((mem.heapUsed / mem.heapTotal) * 100);

    const uptime = uptimeSeconds();

    const activeAlerts = (await dashboard.getAlerts(false)).length;

    const body: AdminStatusResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      uptime_seconds: uptime,
      uptime_human: formatUptime(uptime),
      health,
      costs,
      performance,
      agents,
      channels,
      system: {
        memory_usage_percent: memPercent,
        active_tasks: dashboardState.system_health.active_tasks,
        pending_tasks: dashboardState.system_health.pending_tasks,
      },
      alerts_active: activeAlerts,
    };

    res.json(body);
  } catch (error) {
    console.error("Admin status error:", error);
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

/**
 * GET /admin/logs
 * Returns recent event log entries with optional filtering.
 *
 * Query parameters:
 *   agent   — filter by agent_id
 *   channel — alias for agent (agents map to channels)
 *   level   — filter by log level (debug | info | warn | error)
 *   type    — filter by event type string
 *   limit   — max entries to return (default 100, max 500)
 *   offset  — number of entries to skip (default 0)
 *   since   — ISO timestamp; only return events after this time
 */
router.get("/admin/logs", async (req: Request, res: Response): Promise<void> => {
  try {
    const agentFilter = (req.query.agent ?? req.query.channel ?? "") as string;
    const levelFilter = (req.query.level ?? "") as string;
    const typeFilter = (req.query.type ?? "") as string;
    const since = req.query.since ? new Date(req.query.since as string) : undefined;
    const limit = Math.min(Math.max(parseInt(req.query.limit as string, 10) || 100, 1), 500);
    const offset = Math.max(parseInt(req.query.offset as string, 10) || 0, 0);

    // Fetch events from the event logger
    const allEvents = await eventLogger.getEvents({
      type: typeFilter || undefined,
      level: levelFilter || undefined,
      startTime: since,
    });

    // Apply agent/channel filter (not supported natively by eventLogger)
    let filtered = allEvents;
    if (agentFilter) {
      filtered = filtered.filter(
        (e) => e.agent_id === agentFilter || e.data?.channel === agentFilter,
      );
    }

    // Paginate (newest first)
    const reversed = filtered.reverse();
    const page = reversed.slice(offset, offset + limit);

    const body: AdminLogsResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      total: filtered.length,
      offset,
      limit,
      entries: page,
    };

    res.json(body);
  } catch (error) {
    console.error("Admin logs error:", error);
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

export default router;
