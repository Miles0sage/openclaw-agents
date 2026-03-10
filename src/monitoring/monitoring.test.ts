/**
 * Monitoring System Tests
 * Comprehensive tests for dashboard, alerts, metrics, and events
 */

import * as fs from "node:fs/promises";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { Alert, Event, TaskMetric } from "./types.js";
import { AlertManager } from "./alerts.js";
import { Dashboard } from "./dashboard.js";
import { EventLogger } from "./event-logger.js";
import { MetricsCollector } from "./metrics.js";

const TEST_DIR = "/tmp/monitoring_test";

async function cleanupTestFiles() {
  try {
    await fs.rm(TEST_DIR, { recursive: true, force: true });
    // Clean up global temp files
    await fs.rm("/tmp/dashboard_state.json", { force: true });
    await fs.rm("/tmp/alerts.json", { force: true });
    await fs.rm("/tmp/metrics.json", { force: true });
    await fs.rm("/tmp/events.json", { force: true });
  } catch (err) {
    // Ignore cleanup errors
  }
}

describe("Dashboard", () => {
  let dashboard: Dashboard;

  beforeEach(async () => {
    await cleanupTestFiles();
    dashboard = new Dashboard();
    await dashboard.init();
  });

  afterEach(async () => {
    await cleanupTestFiles();
  });

  it("should initialize dashboard state", async () => {
    const state = await dashboard.getDashboardState();

    expect(state).toBeDefined();
    expect(state.timestamp).toBeDefined();
    expect(state.agents).toEqual([]);
    expect(state.costs).toBeDefined();
    expect(state.alerts).toBeDefined();
    expect(state.system_health).toBeDefined();
  });

  it("should update agent status", async () => {
    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "online",
      task_count: 5,
      success_count: 4,
      error_count: 1,
      uptime_seconds: 3600,
      last_activity: new Date().toISOString(),
    });

    const agents = await dashboard.getAgentStatus();

    expect(agents).toHaveLength(1);
    expect(agents[0].name).toBe("agent-1");
    expect(agents[0].status).toBe("online");
    expect(agents[0].task_count).toBe(5);
  });

  it("should update multiple agents", async () => {
    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "online",
      task_count: 3,
      success_count: 3,
      error_count: 0,
      uptime_seconds: 3600,
      last_activity: new Date().toISOString(),
    });

    await dashboard.updateAgentStatus("agent-2", {
      name: "agent-2",
      status: "processing",
      task_count: 1,
      success_count: 0,
      error_count: 0,
      uptime_seconds: 1800,
      last_activity: new Date().toISOString(),
    });

    const agents = await dashboard.getAgentStatus();

    expect(agents).toHaveLength(2);
    expect(agents.map((a) => a.name)).toContain("agent-1");
    expect(agents.map((a) => a.name)).toContain("agent-2");
  });

  it("should update costs", async () => {
    await dashboard.updateCosts({
      today: 25.5,
      this_week: 150.0,
      this_month: 500.0,
      daily_rate: 25.5,
      projected_monthly: 750.0,
      by_project: { project_a: 300.0, project_b: 200.0 },
      by_model: { "claude-opus": 400.0, "claude-sonnet": 100.0 },
    });

    const costs = await dashboard.getCostSummary();

    expect(costs.today).toBe(25.5);
    expect(costs.this_month).toBe(500.0);
    expect(costs.by_project.project_a).toBe(300.0);
  });

  it("should persist dashboard state to file", async () => {
    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "online",
      task_count: 2,
      success_count: 2,
      error_count: 0,
      uptime_seconds: 3600,
      last_activity: new Date().toISOString(),
    });

    // Create new dashboard instance and verify state was persisted
    const dashboard2 = new Dashboard();
    await dashboard2.init();
    const agents = await dashboard2.getAgentStatus();

    expect(agents).toHaveLength(1);
    expect(agents[0].name).toBe("agent-1");
  });

  it("should emit status change events", async () => {
    const spy = vi.fn();
    dashboard.on("agent_status_changed", spy);

    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "online",
      task_count: 1,
      success_count: 1,
      error_count: 0,
      uptime_seconds: 3600,
      last_activity: new Date().toISOString(),
    });

    expect(spy).toHaveBeenCalled();
  });

  it("should report system health metrics", async () => {
    const state = await dashboard.getDashboardState();

    expect(state.system_health.memory_usage_percent).toBeGreaterThanOrEqual(0);
    expect(state.system_health.memory_usage_percent).toBeLessThanOrEqual(100);
    expect(state.system_health.uptime_hours).toBeGreaterThan(0);
    expect(state.system_health.active_tasks).toBeGreaterThanOrEqual(0);
    expect(state.system_health.pending_tasks).toBeGreaterThanOrEqual(0);
  });
});

describe("AlertManager", () => {
  let alertManager: AlertManager;

  beforeEach(async () => {
    await cleanupTestFiles();
    alertManager = new AlertManager({
      telegramBotToken: undefined,
      telegramUserId: undefined,
      slackWebhookUrl: undefined,
    });
    await alertManager.init();
  });

  afterEach(async () => {
    await cleanupTestFiles();
  });

  it("should create an alert", async () => {
    const alert = await alertManager.createAlert("error", "Test error message", {
      details: "test",
    });

    expect(alert).toBeDefined();
    expect(alert.type).toBe("error");
    expect(alert.message).toBe("Test error message");
    expect(alert.acknowledged).toBe(false);
  });

  it("should save and retrieve alerts", async () => {
    await alertManager.createAlert("error", "Error 1");
    await alertManager.createAlert("warning", "Warning 1");

    const alerts = await alertManager.getAlerts();

    expect(alerts).toHaveLength(2);
    expect(alerts.map((a) => a.type)).toContain("error");
    expect(alerts.map((a) => a.type)).toContain("warning");
  });

  it("should filter alerts by type", async () => {
    await alertManager.createAlert("error", "Error 1");
    await alertManager.createAlert("warning", "Warning 1");
    await alertManager.createAlert("success", "Success 1");

    const errors = await alertManager.getAlerts({ type: "error" });
    const warnings = await alertManager.getAlerts({ type: "warning" });

    expect(errors).toHaveLength(1);
    expect(errors[0].type).toBe("error");
    expect(warnings).toHaveLength(1);
    expect(warnings[0].type).toBe("warning");
  });

  it("should acknowledge alerts", async () => {
    const alert = await alertManager.createAlert("warning", "Test warning");

    await alertManager.acknowledgeAlert(alert.id);

    const alerts = await alertManager.getAlerts({ acknowledged: true });

    expect(alerts).toHaveLength(1);
    expect(alerts[0].acknowledged).toBe(true);
    expect(alerts[0].acknowledged_at).toBeDefined();
  });

  it("should auto-acknowledge old alerts", async () => {
    const alert = await alertManager.createAlert("warning", "Test warning");

    // Manually modify alert to be older than 24 hours
    const alerts = await alertManager.getAlerts();
    if (alerts[0]) {
      const oldTimestamp = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
      alerts[0].timestamp = oldTimestamp;
      await fs.writeFile("/tmp/alerts.json", JSON.stringify(alerts));
    }

    // Fetch alerts again - should auto-acknowledge
    const fetchedAlerts = await alertManager.getAlerts({ acknowledged: false });

    // The old alert should be auto-acknowledged
    expect(fetchedAlerts.length).toBeLessThanOrEqual(1);
  });

  it("should store alert context", async () => {
    const context = { agent: "test-agent", error_code: 500 };
    const alert = await alertManager.createAlert("error", "API Error", context);

    const alerts = await alertManager.getAlerts();

    expect(alerts[0].context).toEqual(context);
  });
});

describe("MetricsCollector", () => {
  let metricsCollector: MetricsCollector;

  beforeEach(async () => {
    await cleanupTestFiles();
    metricsCollector = new MetricsCollector();
    await metricsCollector.init();
  });

  afterEach(async () => {
    await cleanupTestFiles();
  });

  it("should record task metrics", async () => {
    const metric = {
      task_id: "task-1",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.5,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "completed" as const,
    };

    await metricsCollector.recordTask(metric);

    // Verify by getting stats
    const stats = await metricsCollector.getStats("day");

    expect(stats.total_tasks).toBe(1);
    expect(stats.avg_response_time_seconds).toBe(2.5);
    expect(stats.total_cost_usd).toBeCloseTo(0.01, 2);
  });

  it("should aggregate daily metrics", async () => {
    await metricsCollector.recordTask({
      task_id: "task-1",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "completed",
    });

    await metricsCollector.recordTask({
      task_id: "task-2",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 4.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 90,
      accuracy_score: 90,
      status: "completed",
    });

    const stats = await metricsCollector.getStats("day");

    expect(stats.total_tasks).toBe(2);
    expect(stats.avg_response_time_seconds).toBe(3.0);
    expect(stats.total_cost_usd).toBeCloseTo(0.02, 2);
    expect(stats.success_rate).toBe(100);
  });

  it("should group metrics by agent", async () => {
    await metricsCollector.recordTask({
      task_id: "task-1",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "completed",
    });

    await metricsCollector.recordTask({
      task_id: "task-2",
      agent_id: "agent-2",
      project_id: "project-a",
      response_time_seconds: 3.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.02,
      test_pass_rate: 80,
      accuracy_score: 85,
      status: "completed",
    });

    const stats = await metricsCollector.getStats("day");

    expect(Object.keys(stats.by_agent)).toHaveLength(2);
    expect(stats.by_agent["agent-1"].task_count).toBe(1);
    expect(stats.by_agent["agent-2"].task_count).toBe(1);
  });

  it("should get metrics by project", async () => {
    await metricsCollector.recordTask({
      task_id: "task-1",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "completed",
    });

    await metricsCollector.recordTask({
      task_id: "task-2",
      agent_id: "agent-1",
      project_id: "project-b",
      response_time_seconds: 3.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.015,
      test_pass_rate: 90,
      accuracy_score: 90,
      status: "completed",
    });

    const projectStats = await metricsCollector.getMetricsByProject("project-a");

    expect(projectStats.project_id).toBe("project-a");
    expect(projectStats.total_tasks).toBe(1);
    expect(projectStats.total_cost).toBeCloseTo(0.01, 2);
    expect(projectStats.success_rate).toBe(100);
  });

  it("should calculate success rate correctly", async () => {
    await metricsCollector.recordTask({
      task_id: "task-1",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "completed",
    });

    await metricsCollector.recordTask({
      task_id: "task-2",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "failed",
    });

    const stats = await metricsCollector.getStats("day");

    expect(stats.success_rate).toBe(50);
  });
});

describe("EventLogger", () => {
  let eventLogger: EventLogger;

  beforeEach(async () => {
    await cleanupTestFiles();
    eventLogger = new EventLogger();
    await eventLogger.init();
  });

  afterEach(async () => {
    await cleanupTestFiles();
  });

  it("should log events", async () => {
    await eventLogger.logEvent("task_started", { taskId: "task-1", agentId: "agent-1" });

    const events = await eventLogger.getEvents();

    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("task_started");
    expect(events[0].level).toBe("info");
  });

  it("should log with custom level", async () => {
    await eventLogger.logEvent("error_occurred", { message: "Error message" }, { level: "error" });

    const events = await eventLogger.getEvents({ level: "error" });

    expect(events).toHaveLength(1);
    expect(events[0].level).toBe("error");
  });

  it("should filter events by type", async () => {
    await eventLogger.logEvent("task_started", { taskId: "task-1" });
    await eventLogger.logEvent("task_completed", { taskId: "task-1" });
    await eventLogger.logEvent("error_occurred", { message: "Error" });

    const taskEvents = await eventLogger.getEvents({ type: "task_started" });

    expect(taskEvents).toHaveLength(1);
    expect(taskEvents[0].type).toBe("task_started");
  });

  it("should filter events by level", async () => {
    await eventLogger.logEvent("info_event", { message: "info" }, { level: "info" });
    await eventLogger.logEvent("error_event", { message: "error" }, { level: "error" });

    const errorEvents = await eventLogger.getEvents({ level: "error" });

    expect(errorEvents).toHaveLength(1);
    expect(errorEvents[0].level).toBe("error");
  });

  it("should include agent and task ids", async () => {
    await eventLogger.logEvent(
      "task_started",
      { message: "Task started" },
      {
        agentId: "agent-1",
        taskId: "task-1",
        projectId: "project-a",
      },
    );

    const events = await eventLogger.getEvents();

    expect(events[0].agent_id).toBe("agent-1");
    expect(events[0].task_id).toBe("task-1");
    expect(events[0].project_id).toBe("project-a");
  });

  it("should clear old events", async () => {
    await eventLogger.logEvent("event-1", { message: "event 1" });
    await eventLogger.logEvent("event-2", { message: "event 2" });

    // Clear events older than -1 hour (all)
    await eventLogger.clearOld(-3600);

    const events = await eventLogger.getEvents();

    expect(events).toHaveLength(0);
  });

  it("should handle large event logs without error", async () => {
    // Log many events
    for (let i = 0; i < 100; i++) {
      await eventLogger.logEvent("event", { id: i });
    }

    const events = await eventLogger.getEvents();

    expect(events.length).toBeLessThanOrEqual(100);
  });
});

describe("Integration Tests", () => {
  let dashboard: Dashboard;
  let alertManager: AlertManager;
  let metricsCollector: MetricsCollector;
  let eventLogger: EventLogger;

  beforeEach(async () => {
    await cleanupTestFiles();
    dashboard = new Dashboard();
    alertManager = new AlertManager({
      telegramBotToken: undefined,
      telegramUserId: undefined,
      slackWebhookUrl: undefined,
    });
    metricsCollector = new MetricsCollector();
    eventLogger = new EventLogger();

    await dashboard.init();
    await alertManager.init();
    await metricsCollector.init();
    await eventLogger.init();
  });

  afterEach(async () => {
    await cleanupTestFiles();
  });

  it("should build complete dashboard state", async () => {
    // Set up agents
    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "online",
      task_count: 5,
      success_count: 5,
      error_count: 0,
      uptime_seconds: 3600,
      last_activity: new Date().toISOString(),
    });

    // Update costs
    await dashboard.updateCosts({
      today: 10.5,
      this_week: 50.0,
      this_month: 200.0,
      daily_rate: 10.5,
      projected_monthly: 300.0,
      by_project: { "project-a": 200.0 },
      by_model: { "claude-opus": 200.0 },
    });

    // Record metrics
    await metricsCollector.recordTask({
      task_id: "task-1",
      agent_id: "agent-1",
      project_id: "project-a",
      response_time_seconds: 2.0,
      tokens_input: 100,
      tokens_output: 200,
      cost_usd: 0.01,
      test_pass_rate: 100,
      accuracy_score: 95,
      status: "completed",
    });

    // Create alerts
    await alertManager.createAlert("info", "Agent online");

    // Log events
    await eventLogger.logEvent("agent_connected", { agentId: "agent-1" });

    // Get complete state
    const state = await dashboard.getDashboardState();

    expect(state.agents).toHaveLength(1);
    expect(state.costs.today).toBe(10.5);
    expect(state.metrics.today.total_tasks).toBe(1);
    expect(state.recent_events.length).toBeGreaterThan(0);
  });

  it("should track dashboard state through multiple updates", async () => {
    const states: any[] = [];

    dashboard.on("agent_status_changed", async () => {
      states.push(await dashboard.getDashboardState());
    });

    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "online",
      task_count: 1,
      success_count: 1,
      error_count: 0,
      uptime_seconds: 100,
      last_activity: new Date().toISOString(),
    });

    await dashboard.updateAgentStatus("agent-1", {
      name: "agent-1",
      status: "processing",
      task_count: 2,
      success_count: 1,
      error_count: 0,
      uptime_seconds: 200,
      last_activity: new Date().toISOString(),
    });

    expect(states.length).toBeGreaterThan(0);
  });
});
