/**
 * Monitoring Dashboard
 * Real-time visibility into agent activities, costs, task progress
 */

import { EventEmitter } from "node:events";
import * as fs from "node:fs/promises";
import type {
  AgentStatus,
  CostSummary,
  Alert,
  DashboardState,
  AggregatedMetrics,
} from "./types.js";
import { alertManager } from "./alerts.js";
import { eventLogger } from "./event-logger.js";
import { metricsCollector } from "./metrics.js";

const DASHBOARD_STATE_FILE = "/tmp/dashboard_state.json";

export class Dashboard extends EventEmitter {
  private initialized = false;
  private agents: Map<string, AgentStatus> = new Map();
  private costs: CostSummary = {
    today: 0,
    this_week: 0,
    this_month: 0,
    by_project: {},
    by_model: {},
    daily_rate: 0,
    projected_monthly: 0,
    currency: "USD",
  };

  async init(): Promise<void> {
    if (this.initialized) return;

    try {
      // Load saved state
      await this.loadState();
      this.initialized = true;
    } catch (err) {
      console.error("Failed to initialize Dashboard:", err);
    }
  }

  async updateAgentStatus(agentId: string, status: Partial<AgentStatus>): Promise<void> {
    await this.init();

    const existing = this.agents.get(agentId) || {
      name: agentId,
      status: "offline" as const,
      uptime_seconds: 0,
      last_activity: new Date().toISOString(),
      task_count: 0,
      success_count: 0,
      error_count: 0,
    };

    const updated = { ...existing, ...status };
    this.agents.set(agentId, updated);

    this.emit("agent_status_changed", { agentId, status: updated });
    await this.saveState();
  }

  async updateCosts(costs: Partial<CostSummary>): Promise<void> {
    await this.init();

    this.costs = { ...this.costs, ...costs };

    // Check for cost alerts
    if (costs.today && costs.today > 50) {
      await alertManager.createAlert("warning", "Daily cost exceeded $50", {
        daily_cost: costs.today,
      });
    }

    this.emit("costs_updated", this.costs);
    await this.saveState();
  }

  async getAgentStatus(): Promise<AgentStatus[]> {
    await this.init();
    return Array.from(this.agents.values());
  }

  async getCostSummary(): Promise<CostSummary> {
    await this.init();
    return this.costs;
  }

  async getAlerts(acknowledged?: boolean): Promise<Alert[]> {
    const filter = acknowledged !== undefined ? { acknowledged } : undefined;
    return alertManager.getAlerts(filter);
  }

  async getMetrics(): Promise<{
    today: AggregatedMetrics;
    this_week: AggregatedMetrics;
    this_month: AggregatedMetrics;
  }> {
    return {
      today: await metricsCollector.getStats("day"),
      this_week: await metricsCollector.getStats("week"),
      this_month: await metricsCollector.getStats("month"),
    };
  }

  async getDashboardState(): Promise<DashboardState> {
    await this.init();

    const events = await eventLogger.getEvents({
      startTime: new Date(Date.now() - 3600000), // Last hour
    });

    const metrics = await this.getMetrics();

    return {
      timestamp: new Date().toISOString(),
      agents: Array.from(this.agents.values()),
      costs: this.costs,
      alerts: await this.getAlerts(false),
      recent_events: events.slice(-50),
      metrics,
      system_health: {
        memory_usage_percent: this.getMemoryUsage(),
        uptime_hours: process.uptime() / 3600,
        active_tasks: Array.from(this.agents.values()).filter((a) => a.status === "processing")
          .length,
        pending_tasks: Array.from(this.agents.values()).reduce((sum, a) => sum + a.task_count, 0),
      },
    };
  }

  onStatusChange(callback: (state: DashboardState) => void): void {
    this.on("agent_status_changed", async () => {
      const state = await this.getDashboardState();
      callback(state);
    });

    this.on("costs_updated", async () => {
      const state = await this.getDashboardState();
      callback(state);
    });
  }

  private async loadState(): Promise<void> {
    try {
      const content = await fs.readFile(DASHBOARD_STATE_FILE, "utf-8");
      const saved = JSON.parse(content) as DashboardState;

      // Restore agents
      for (const agent of saved.agents) {
        this.agents.set(agent.name, agent);
      }

      this.costs = saved.costs;
    } catch (err) {
      // File doesn't exist or is invalid, start fresh
      console.log("Starting with fresh dashboard state");
    }
  }

  private async saveState(): Promise<void> {
    try {
      const state = await this.getDashboardState();
      await fs.writeFile(DASHBOARD_STATE_FILE, JSON.stringify(state, null, 0));
    } catch (err) {
      console.error("Failed to save dashboard state:", err);
    }
  }

  private getMemoryUsage(): number {
    if (typeof process !== "undefined" && typeof process.memoryUsage === "function") {
      const usage = process.memoryUsage();
      const totalMemory = usage.heapTotal;
      const usedMemory = usage.heapUsed;
      return Math.round((usedMemory / totalMemory) * 100);
    }
    return 0;
  }
}

export const dashboard = new Dashboard();
