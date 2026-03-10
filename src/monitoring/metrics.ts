/**
 * Metrics Collector
 * Track per-task metrics and aggregate statistics
 */

import * as fs from "node:fs/promises";
import type { TaskMetric, AggregatedMetrics } from "./types.js";

const METRICS_FILE = "/tmp/metrics.json";

export class MetricsCollector {
  private initialized = false;

  async init(): Promise<void> {
    if (this.initialized) return;

    try {
      // Create metrics file if it doesn't exist
      try {
        await fs.access(METRICS_FILE);
      } catch {
        await fs.writeFile(METRICS_FILE, JSON.stringify([]));
      }

      this.initialized = true;
    } catch (err) {
      console.error("Failed to initialize MetricsCollector:", err);
    }
  }

  async recordTask(taskResult: Omit<TaskMetric, "timestamp">): Promise<void> {
    await this.init();

    const metric: TaskMetric = {
      ...taskResult,
      timestamp: new Date().toISOString(),
    };

    try {
      const metrics = await this.readMetrics();
      metrics.push(metric);

      // Keep only last 10000 metrics
      const metricsToWrite = metrics.slice(-10000);
      await fs.writeFile(METRICS_FILE, JSON.stringify(metricsToWrite, null, 0));
    } catch (err) {
      console.error("Failed to record task metric:", err);
    }
  }

  async getStats(period: "day" | "week" | "month"): Promise<AggregatedMetrics> {
    await this.init();

    try {
      const metrics = await this.readMetrics();
      const now = new Date();
      let startDate: Date;

      if (period === "day") {
        startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      } else if (period === "week") {
        const dayOfWeek = now.getDay();
        startDate = new Date(now);
        startDate.setDate(now.getDate() - dayOfWeek);
      } else {
        startDate = new Date(now.getFullYear(), now.getMonth(), 1);
      }

      const filteredMetrics = metrics.filter((m) => new Date(m.timestamp) >= startDate);

      const aggregated = this.aggregateMetrics(filteredMetrics, period, startDate, now);
      return aggregated;
    } catch (err) {
      console.error("Failed to get stats:", err);
      return this.getEmptyStats(period);
    }
  }

  async getMetricsByProject(
    projectId: string,
  ): Promise<{
    project_id: string;
    total_tasks: number;
    total_cost: number;
    avg_response_time: number;
    success_rate: number;
    by_agent: Record<string, { task_count: number; cost: number }>;
  }> {
    await this.init();

    try {
      const metrics = await this.readMetrics();
      const projectMetrics = metrics.filter((m) => m.project_id === projectId);

      if (projectMetrics.length === 0) {
        return {
          project_id: projectId,
          total_tasks: 0,
          total_cost: 0,
          avg_response_time: 0,
          success_rate: 0,
          by_agent: {},
        };
      }

      const totalCost = projectMetrics.reduce((sum, m) => sum + m.cost_usd, 0);
      const avgResponseTime =
        projectMetrics.reduce((sum, m) => sum + m.response_time_seconds, 0) / projectMetrics.length;
      const successCount = projectMetrics.filter((m) => m.status === "completed").length;
      const successRate = (successCount / projectMetrics.length) * 100;

      const byAgent: Record<string, { task_count: number; cost: number }> = {};
      for (const metric of projectMetrics) {
        if (!byAgent[metric.agent_id]) {
          byAgent[metric.agent_id] = { task_count: 0, cost: 0 };
        }
        byAgent[metric.agent_id].task_count += 1;
        byAgent[metric.agent_id].cost += metric.cost_usd;
      }

      return {
        project_id: projectId,
        total_tasks: projectMetrics.length,
        total_cost: Math.round(totalCost * 10000) / 10000,
        avg_response_time: Math.round(avgResponseTime * 100) / 100,
        success_rate: Math.round(successRate * 100) / 100,
        by_agent: byAgent,
      };
    } catch (err) {
      console.error("Failed to get project metrics:", err);
      return {
        project_id: projectId,
        total_tasks: 0,
        total_cost: 0,
        avg_response_time: 0,
        success_rate: 0,
        by_agent: {},
      };
    }
  }

  private aggregateMetrics(
    metrics: TaskMetric[],
    period: string,
    startDate: Date,
    endDate: Date,
  ): AggregatedMetrics {
    if (metrics.length === 0) {
      return this.getEmptyStats(period as "day" | "week" | "month");
    }

    const totalTasks = metrics.length;
    const totalResponseTime = metrics.reduce((sum, m) => sum + m.response_time_seconds, 0);
    const avgResponseTime = totalResponseTime / totalTasks;

    const totalInputTokens = metrics.reduce((sum, m) => sum + m.tokens_input, 0);
    const totalOutputTokens = metrics.reduce((sum, m) => sum + m.tokens_output, 0);
    const totalCost = metrics.reduce((sum, m) => sum + m.cost_usd, 0);

    const avgTestPassRate = metrics.reduce((sum, m) => sum + m.test_pass_rate, 0) / totalTasks;
    const avgAccuracyScore = metrics.reduce((sum, m) => sum + m.accuracy_score, 0) / totalTasks;

    const completedTasks = metrics.filter((m) => m.status === "completed").length;
    const successRate = (completedTasks / totalTasks) * 100;

    // Group by agent
    const byAgent: Record<
      string,
      { task_count: number; avg_response_time: number; success_rate: number }
    > = {};
    for (const metric of metrics) {
      if (!byAgent[metric.agent_id]) {
        byAgent[metric.agent_id] = { task_count: 0, avg_response_time: 0, success_rate: 0 };
      }
      byAgent[metric.agent_id].task_count += 1;
    }

    for (const agentId in byAgent) {
      const agentMetrics = metrics.filter((m) => m.agent_id === agentId);
      const agentResponseTime =
        agentMetrics.reduce((sum, m) => sum + m.response_time_seconds, 0) / agentMetrics.length;
      const agentCompleted = agentMetrics.filter((m) => m.status === "completed").length;
      const agentSuccessRate = (agentCompleted / agentMetrics.length) * 100;

      byAgent[agentId].avg_response_time = Math.round(agentResponseTime * 100) / 100;
      byAgent[agentId].success_rate = Math.round(agentSuccessRate * 100) / 100;
    }

    // Group by project
    const byProject: Record<string, { task_count: number; total_cost: number }> = {};
    for (const metric of metrics) {
      if (!byProject[metric.project_id]) {
        byProject[metric.project_id] = { task_count: 0, total_cost: 0 };
      }
      byProject[metric.project_id].task_count += 1;
      byProject[metric.project_id].total_cost += metric.cost_usd;
    }

    return {
      period: period as "day" | "week" | "month",
      start_date: startDate.toISOString(),
      end_date: endDate.toISOString(),
      total_tasks: totalTasks,
      avg_response_time_seconds: Math.round(avgResponseTime * 100) / 100,
      total_tokens_input: totalInputTokens,
      total_tokens_output: totalOutputTokens,
      total_cost_usd: Math.round(totalCost * 10000) / 10000,
      avg_test_pass_rate: Math.round(avgTestPassRate * 100) / 100,
      avg_accuracy_score: Math.round(avgAccuracyScore * 100) / 100,
      success_rate: Math.round(successRate * 100) / 100,
      by_agent: byAgent,
      by_project: byProject,
    };
  }

  private getEmptyStats(period: "day" | "week" | "month"): AggregatedMetrics {
    const now = new Date();
    let startDate: Date;

    if (period === "day") {
      startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    } else if (period === "week") {
      const dayOfWeek = now.getDay();
      startDate = new Date(now);
      startDate.setDate(now.getDate() - dayOfWeek);
    } else {
      startDate = new Date(now.getFullYear(), now.getMonth(), 1);
    }

    return {
      period,
      start_date: startDate.toISOString(),
      end_date: now.toISOString(),
      total_tasks: 0,
      avg_response_time_seconds: 0,
      total_tokens_input: 0,
      total_tokens_output: 0,
      total_cost_usd: 0,
      avg_test_pass_rate: 0,
      avg_accuracy_score: 0,
      success_rate: 0,
      by_agent: {},
      by_project: {},
    };
  }

  private async readMetrics(): Promise<TaskMetric[]> {
    try {
      const content = await fs.readFile(METRICS_FILE, "utf-8");
      return JSON.parse(content) || [];
    } catch {
      return [];
    }
  }
}

export const metricsCollector = new MetricsCollector();
