/**
 * Heartbeat Monitor for Agent Health Checks
 * Detects stale and timeout agents, sends alerts, and auto-recovers
 */

import { AlertManager } from "./alerts.js";

export interface AgentActivity {
  agentId: string;
  startedAt: number; // timestamp in ms when task started
  lastActivityAt: number; // timestamp in ms of last activity
  taskId?: string;
  status: "running" | "idle";
}

export interface HeartbeatMonitorConfig {
  checkIntervalMs?: number; // how often to run health checks (default: 30s)
  staleThresholdMs?: number; // idle >5min is stale (default: 5 min)
  timeoutThresholdMs?: number; // running >30min is timeout (default: 30 min)
  staleWarningOnlyOnce?: boolean; // only alert once per stale agent (default: true)
}

export class HeartbeatMonitor {
  private inFlightAgents: Map<string, AgentActivity> = new Map();
  private intervalHandle: NodeJS.Timeout | null = null;
  private alertManager: AlertManager;
  private config: Required<HeartbeatMonitorConfig>;
  private staleCounts: Map<string, number> = new Map(); // track how many times we've alerted for stale
  private isRunning = false;

  constructor(alertManager?: AlertManager, config?: HeartbeatMonitorConfig) {
    this.alertManager = alertManager || new AlertManager();
    this.config = {
      checkIntervalMs: config?.checkIntervalMs || 30000, // 30 seconds
      staleThresholdMs: config?.staleThresholdMs || 5 * 60 * 1000, // 5 minutes
      timeoutThresholdMs: config?.timeoutThresholdMs || 30 * 60 * 1000, // 30 minutes
      staleWarningOnlyOnce: config?.staleWarningOnlyOnce !== false,
    };
  }

  /**
   * Start the background health check loop
   */
  async start(): Promise<void> {
    if (this.isRunning) {
      console.warn("HeartbeatMonitor: already running");
      return;
    }

    this.isRunning = true;
    await this.alertManager.init();
    console.log(`⏱️ HeartbeatMonitor: started (check interval: ${this.config.checkIntervalMs}ms)`);

    // Run checks immediately, then on interval
    await this.runHealthChecks();
    this.intervalHandle = setInterval(async () => {
      try {
        await this.runHealthChecks();
      } catch (err) {
        console.error("HeartbeatMonitor: error in health check loop:", err);
      }
    }, this.config.checkIntervalMs);

    // Don't keep process alive if this is the only timer
    this.intervalHandle?.unref?.();
  }

  /**
   * Stop the background health check loop
   */
  stop(): void {
    if (this.intervalHandle) {
      clearInterval(this.intervalHandle);
      this.intervalHandle = null;
    }
    this.isRunning = false;
    console.log("⏱️ HeartbeatMonitor: stopped");
  }

  /**
   * Register an in-flight agent task
   */
  registerAgent(agentId: string, taskId?: string): void {
    const now = Date.now();
    this.inFlightAgents.set(agentId, {
      agentId,
      startedAt: now,
      lastActivityAt: now,
      taskId,
      status: "running",
    });
    this.staleCounts.delete(agentId); // reset stale count on new task
  }

  /**
   * Update last activity timestamp for an agent
   */
  updateActivity(agentId: string): void {
    const agent = this.inFlightAgents.get(agentId);
    if (agent) {
      agent.lastActivityAt = Date.now();
      agent.status = "running";
    }
  }

  /**
   * Mark an agent as idle (waiting for something)
   */
  markIdle(agentId: string): void {
    const agent = this.inFlightAgents.get(agentId);
    if (agent) {
      agent.status = "idle";
    }
  }

  /**
   * Unregister an in-flight agent task (task completed or failed)
   */
  unregisterAgent(agentId: string): void {
    this.inFlightAgents.delete(agentId);
    this.staleCounts.delete(agentId);
  }

  /**
   * Get all in-flight agents
   */
  getInFlightAgents(): AgentActivity[] {
    return Array.from(this.inFlightAgents.values());
  }

  /**
   * Run health checks on all in-flight agents
   */
  private async runHealthChecks(): Promise<void> {
    const now = Date.now();
    const agents = Array.from(this.inFlightAgents.entries());

    for (const [agentId, agent] of agents) {
      try {
        const elapsedMs = now - agent.startedAt;
        const idleMs = now - agent.lastActivityAt;

        // Check for timeout: task running >30min
        if (elapsedMs > this.config.timeoutThresholdMs) {
          await this.handleTimeout(agentId, agent, elapsedMs);
          continue; // Don't also alert on stale
        }

        // Check for stale: idle >5min but still <30min
        if (idleMs > this.config.staleThresholdMs && elapsedMs < this.config.timeoutThresholdMs) {
          await this.handleStale(agentId, agent, idleMs);
        }
      } catch (err) {
        console.error(`HeartbeatMonitor: error checking agent ${agentId}:`, err);
      }
    }
  }

  /**
   * Handle stale agent detection
   */
  private async handleStale(agentId: string, agent: AgentActivity, idleMs: number): Promise<void> {
    const staleCount = this.staleCounts.get(agentId) || 0;

    // Only alert once per stale agent if configured
    if (this.config.staleWarningOnlyOnce && staleCount > 0) {
      return;
    }

    const idleSeconds = Math.floor(idleMs / 1000);
    const message = `⚠️ Stale agent detected: ${agentId} idle for ${idleSeconds}s`;

    console.warn(message);

    await this.alertManager.createAlert("warning", message, {
      agentId,
      idleMs,
      idleSeconds,
      taskId: agent.taskId,
      elapsedMs: Date.now() - agent.startedAt,
      source: "heartbeat-monitor",
    });

    this.staleCounts.set(agentId, staleCount + 1);
  }

  /**
   * Handle timeout agent detection and recovery
   */
  private async handleTimeout(
    agentId: string,
    agent: AgentActivity,
    elapsedMs: number,
  ): Promise<void> {
    const elapsedSeconds = Math.floor(elapsedMs / 1000);
    const elapsedMinutes = Math.floor(elapsedMs / 60000);
    const message = `❌ Timeout: agent ${agentId} running for ${elapsedMinutes}min (task: ${agent.taskId || "unknown"})`;

    console.error(message);

    // Create error alert
    await this.alertManager.createAlert("error", message, {
      agentId,
      taskId: agent.taskId,
      elapsedMs,
      elapsedSeconds,
      elapsedMinutes,
      source: "heartbeat-monitor",
    });

    // Auto-recover: unregister the stale task
    this.inFlightAgents.delete(agentId);
    this.staleCounts.delete(agentId);

    // TODO: If you have a task queue, mark task as failed and retry:
    // await taskQueue.updateStatus(agent.taskId, "failed", {
    //   reason: "heartbeat_timeout",
    //   elapsedMs
    // });
    // await taskQueue.addTask({ ...originalTask, retryCount: (retryCount || 0) + 1 });

    console.log(`   ✅ Recovered: agent ${agentId} removed from in-flight, ready for next task`);
  }
}

/**
 * Global heartbeat monitor instance
 */
export let heartbeatMonitor: HeartbeatMonitor | null = null;

/**
 * Initialize and start the global heartbeat monitor
 */
export async function initHeartbeatMonitor(
  alertManager?: AlertManager,
  config?: HeartbeatMonitorConfig,
): Promise<HeartbeatMonitor> {
  if (heartbeatMonitor) {
    console.warn("HeartbeatMonitor: already initialized");
    return heartbeatMonitor;
  }

  heartbeatMonitor = new HeartbeatMonitor(alertManager, config);
  await heartbeatMonitor.start();
  return heartbeatMonitor;
}

/**
 * Stop the global heartbeat monitor
 */
export function stopHeartbeatMonitor(): void {
  if (heartbeatMonitor) {
    heartbeatMonitor.stop();
    heartbeatMonitor = null;
  }
}
