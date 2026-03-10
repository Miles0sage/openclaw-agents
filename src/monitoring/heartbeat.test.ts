/**
 * Heartbeat Monitor Tests
 * Tests for agent health checks, stale detection, and timeout recovery
 */

import * as fs from "node:fs/promises";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { AlertManager } from "./alerts.js";
import { HeartbeatMonitor, initHeartbeatMonitor, stopHeartbeatMonitor } from "./heartbeat.js";

const ALERTS_FILE = "/tmp/alerts.json";

async function cleanupAlerts() {
  try {
    await fs.rm(ALERTS_FILE, { force: true });
  } catch {
    // ignore
  }
}

describe("HeartbeatMonitor", () => {
  let monitor: HeartbeatMonitor;
  let alertManager: AlertManager;

  beforeEach(async () => {
    await cleanupAlerts();
    alertManager = new AlertManager();
    await alertManager.init();
    monitor = new HeartbeatMonitor(alertManager, {
      checkIntervalMs: 100, // fast checks for tests
      staleThresholdMs: 500, // 500ms for tests
      timeoutThresholdMs: 1000, // 1s for tests
    });
  });

  afterEach(async () => {
    monitor.stop();
    await cleanupAlerts();
  });

  describe("Agent Registration", () => {
    it("should register an in-flight agent", () => {
      monitor.registerAgent("agent-1", "task-1");
      const agents = monitor.getInFlightAgents();

      expect(agents).toHaveLength(1);
      expect(agents[0].agentId).toBe("agent-1");
      expect(agents[0].taskId).toBe("task-1");
      expect(agents[0].status).toBe("running");
    });

    it("should unregister an agent", () => {
      monitor.registerAgent("agent-1", "task-1");
      monitor.unregisterAgent("agent-1");
      const agents = monitor.getInFlightAgents();

      expect(agents).toHaveLength(0);
    });

    it("should handle multiple agents", () => {
      monitor.registerAgent("agent-1", "task-1");
      monitor.registerAgent("agent-2", "task-2");
      monitor.registerAgent("agent-3", "task-3");
      const agents = monitor.getInFlightAgents();

      expect(agents).toHaveLength(3);
      expect(agents.map((a) => a.agentId)).toEqual(["agent-1", "agent-2", "agent-3"]);
    });
  });

  describe("Activity Tracking", () => {
    it("should update last activity timestamp", async () => {
      monitor.registerAgent("agent-1", "task-1");
      const before = monitor.getInFlightAgents()[0].lastActivityAt;

      // Wait a bit and update
      await new Promise((r) => setTimeout(r, 100));
      monitor.updateActivity("agent-1");
      const after = monitor.getInFlightAgents()[0].lastActivityAt;

      expect(after).toBeGreaterThan(before);
    });

    it("should mark agent as idle", () => {
      monitor.registerAgent("agent-1", "task-1");
      monitor.markIdle("agent-1");
      const agent = monitor.getInFlightAgents()[0];

      expect(agent.status).toBe("idle");
    });

    it("should set status back to running on updateActivity", () => {
      monitor.registerAgent("agent-1", "task-1");
      monitor.markIdle("agent-1");
      monitor.updateActivity("agent-1");
      const agent = monitor.getInFlightAgents()[0];

      expect(agent.status).toBe("running");
    });
  });

  describe("Stale Detection", () => {
    it("should detect stale agents (idle >5min threshold)", async () => {
      monitor.registerAgent("agent-1", "task-1");

      // Start monitor
      await monitor.start();

      // Simulate idle: don't call updateActivity, let time pass
      await new Promise((r) => setTimeout(r, 600)); // Wait for threshold + buffer

      // Wait for health check to run
      await new Promise((r) => setTimeout(r, 150));

      // Check that alert was created
      const alerts = await alertManager.getAlerts();
      const staleAlerts = alerts.filter((a) => a.type === "warning");

      expect(staleAlerts.length).toBeGreaterThan(0);
      expect(staleAlerts[0].message).toContain("Stale agent");
      expect(staleAlerts[0].message).toContain("agent-1");
    });

    it("should only alert once per stale agent", async () => {
      monitor.registerAgent("agent-1", "task-1");

      // Start monitor
      await monitor.start();

      // Simulate idle long enough to trigger multiple checks
      await new Promise((r) => setTimeout(r, 600));
      await new Promise((r) => setTimeout(r, 150)); // First check

      const alertsAfterFirst = await alertManager.getAlerts({ type: "warning" });
      const firstCount = alertsAfterFirst.length;

      // Wait for another check cycle
      await new Promise((r) => setTimeout(r, 150));

      const alertsAfterSecond = await alertManager.getAlerts({ type: "warning" });
      const secondCount = alertsAfterSecond.length;

      // Should not have created new alerts (staleWarningOnlyOnce is true by default)
      expect(secondCount).toBe(firstCount);
    });

    it("should alert multiple times if staleWarningOnlyOnce=false", async () => {
      const config = {
        checkIntervalMs: 100,
        staleThresholdMs: 500,
        timeoutThresholdMs: 2000,
        staleWarningOnlyOnce: false,
      };
      const localMonitor = new HeartbeatMonitor(alertManager, config);
      localMonitor.registerAgent("agent-1", "task-1");

      await localMonitor.start();

      // Simulate idle long enough for multiple checks
      await new Promise((r) => setTimeout(r, 600));
      await new Promise((r) => setTimeout(r, 150)); // First check

      const alertsAfterFirst = await alertManager.getAlerts({ type: "warning" });
      const firstCount = alertsAfterFirst.filter((a) => a.context?.agentId === "agent-1").length;

      // Wait for another check cycle
      await new Promise((r) => setTimeout(r, 150));

      const alertsAfterSecond = await alertManager.getAlerts({ type: "warning" });
      const secondCount = alertsAfterSecond.filter((a) => a.context?.agentId === "agent-1").length;

      // Should have created new alerts
      expect(secondCount).toBeGreaterThan(firstCount);

      localMonitor.stop();
    });
  });

  describe("Timeout Detection", () => {
    it("should detect timeout agents (running >30min threshold)", async () => {
      monitor.registerAgent("agent-1", "task-1");

      // Start monitor
      await monitor.start();

      // Simulate timeout: don't call updateActivity, let time pass
      await new Promise((r) => setTimeout(r, 1100)); // Wait for threshold + buffer

      // Wait for health check to run
      await new Promise((r) => setTimeout(r, 150));

      // Check that alert was created
      const alerts = await alertManager.getAlerts();
      const errorAlerts = alerts.filter((a) => a.type === "error");

      expect(errorAlerts.length).toBeGreaterThan(0);
      expect(errorAlerts[0].message).toContain("Timeout");
      expect(errorAlerts[0].message).toContain("agent-1");
    });

    it("should auto-recover timeout agents", async () => {
      monitor.registerAgent("agent-1", "task-1");
      expect(monitor.getInFlightAgents()).toHaveLength(1);

      // Start monitor
      await monitor.start();

      // Simulate timeout
      await new Promise((r) => setTimeout(r, 1100));
      await new Promise((r) => setTimeout(r, 150)); // Wait for health check

      // Agent should be removed from in-flight
      const agents = monitor.getInFlightAgents();
      expect(agents).toHaveLength(0);
    });

    it("should prefer timeout over stale alert", async () => {
      // In this test, stale checks happen first, but timeout should result in auto-recovery
      // The behavior is: if timeout is detected, agent is removed, so we get timeout alert
      // (not stale alert) once the timeout threshold is exceeded
      monitor.registerAgent("agent-1", "task-1");

      await monitor.start();

      // Simulate timeout (which is >stale threshold)
      await new Promise((r) => setTimeout(r, 1100));
      await new Promise((r) => setTimeout(r, 150));

      const alerts = await alertManager.getAlerts();

      // Should have at least one error (timeout) alert
      const errorAlerts = alerts.filter((a) => a.type === "error");
      expect(errorAlerts.length).toBeGreaterThan(0);

      // Verify that timeout alert exists with proper context
      const timeoutAlert = errorAlerts.find((a) => a.message.includes("Timeout"));
      expect(timeoutAlert).toBeDefined();
      expect(timeoutAlert?.context?.agentId).toBe("agent-1");
    });
  });

  describe("Activity Updates Prevent Detection", () => {
    it("should not alert if agent is actively updated", async () => {
      monitor.registerAgent("agent-1", "task-1");

      await monitor.start();

      // Actively update before thresholds are hit
      const interval = setInterval(() => {
        monitor.updateActivity("agent-1");
      }, 200);

      // Let checks run a few times
      await new Promise((r) => setTimeout(r, 600));

      clearInterval(interval);

      const alerts = await alertManager.getAlerts();
      expect(alerts.length).toBe(0);
    });
  });

  describe("Global Monitor Functions", () => {
    afterEach(async () => {
      stopHeartbeatMonitor();
    });

    it("should initialize and start global monitor", async () => {
      const global = await initHeartbeatMonitor(alertManager, {
        checkIntervalMs: 100,
        staleThresholdMs: 500,
      });

      expect(global).toBeDefined();
      expect(global.getInFlightAgents()).toHaveLength(0);

      global.registerAgent("test-agent");
      expect(global.getInFlightAgents()).toHaveLength(1);
    });

    it("should stop global monitor", async () => {
      const global = await initHeartbeatMonitor(alertManager);
      global.registerAgent("test-agent");

      stopHeartbeatMonitor();

      // After stopping, should not be running
      expect(global.getInFlightAgents()).toHaveLength(1); // still registered
    });
  });

  describe("Error Handling", () => {
    it("should not crash on error during health check", async () => {
      monitor.registerAgent("agent-1", "task-1");

      // Spy on console.error to verify error is logged
      const consoleErrorSpy = vi.spyOn(console, "error");

      // Force an error by breaking something
      const origAlertCreate = alertManager.createAlert.bind(alertManager);
      vi.spyOn(alertManager, "createAlert").mockImplementationOnce(async () => {
        throw new Error("Test error");
      });

      await monitor.start();
      await new Promise((r) => setTimeout(r, 600)); // Trigger stale condition
      await new Promise((r) => setTimeout(r, 150)); // Wait for check

      // Should log error but not crash
      expect(consoleErrorSpy).toHaveBeenCalled();

      // Restore
      alertManager.createAlert = origAlertCreate;

      // Monitor should still work after error
      expect(monitor.getInFlightAgents()).toHaveLength(1);
    });
  });

  describe("Alert Context", () => {
    it("should include full context in stale alerts", async () => {
      monitor.registerAgent("agent-1", "task-123");

      await monitor.start();
      await new Promise((r) => setTimeout(r, 600));
      await new Promise((r) => setTimeout(r, 150));

      const alerts = await alertManager.getAlerts({ type: "warning" });

      expect(alerts.length).toBeGreaterThan(0);
      const alert = alerts[0];
      expect(alert.context?.agentId).toBe("agent-1");
      expect(alert.context?.taskId).toBe("task-123");
      expect(alert.context?.idleMs).toBeDefined();
      expect(alert.context?.source).toBe("heartbeat-monitor");
    });

    it("should include full context in timeout alerts", async () => {
      monitor.registerAgent("agent-2", "task-456");

      await monitor.start();
      await new Promise((r) => setTimeout(r, 1100));
      await new Promise((r) => setTimeout(r, 150));

      const alerts = await alertManager.getAlerts({ type: "error" });

      expect(alerts.length).toBeGreaterThan(0);
      const alert = alerts[0];
      expect(alert.context?.agentId).toBe("agent-2");
      expect(alert.context?.taskId).toBe("task-456");
      expect(alert.context?.elapsedMs).toBeDefined();
      expect(alert.context?.elapsedMinutes).toBeDefined();
      expect(alert.context?.source).toBe("heartbeat-monitor");
    });
  });
});
