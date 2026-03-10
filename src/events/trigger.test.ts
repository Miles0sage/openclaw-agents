/**
 * Test Suite for Event Trigger System
 * Validates TriggerEngine functionality and event-driven automation patterns
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  handleQualityGatePassed,
  handleTestFailed,
  handleCostAlert,
  handleAgentTimeout,
  handleWorkflowCompleted,
  handleBuildStarted,
  handleBuildCompleted,
  handleDeploymentStarted,
  handleSecurityAlert,
  type QualityGatePassedData,
  type TestFailedData,
  type CostAlertData,
  type AgentTimeoutData,
  type WorkflowCompletedData,
} from "./event-handlers.js";
import {
  TriggerEngine,
  getTriggerEngine,
  resetTriggerEngine,
  type EventTrigger,
} from "./trigger-engine.js";

describe("TriggerEngine", () => {
  let engine: TriggerEngine;

  beforeEach(() => {
    engine = new TriggerEngine();
  });

  afterEach(() => {
    engine.clearAll();
  });

  describe("Registration and Firing", () => {
    it("should register and fire a basic trigger", async () => {
      const actionCalls: any[] = [];

      const trigger: EventTrigger = {
        eventType: "test_event",
        actions: [async (data) => actionCalls.push(data)],
        description: "Test trigger",
      };

      engine.registerTrigger(trigger);
      await engine.emitEvent("test_event", { value: "test" });

      // Give async execution time to complete
      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(actionCalls).toHaveLength(1);
      expect(actionCalls[0].value).toBe("test");
    });

    it("should handle multiple actions in a trigger", async () => {
      const calls: string[] = [];

      const trigger: EventTrigger = {
        eventType: "multi_action",
        actions: [
          async () => calls.push("action1"),
          async () => calls.push("action2"),
          async () => calls.push("action3"),
        ],
        description: "Multi-action trigger",
      };

      engine.registerTrigger(trigger);
      await engine.emitEvent("multi_action", {});

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(calls).toEqual(["action1", "action2", "action3"]);
    });

    it("should support multiple triggers for the same event", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "multi_trigger",
        actions: [async () => calls.push("trigger1")],
        description: "First trigger",
      });

      engine.registerTrigger({
        eventType: "multi_trigger",
        actions: [async () => calls.push("trigger2")],
        description: "Second trigger",
      });

      engine.registerTrigger({
        eventType: "multi_trigger",
        actions: [async () => calls.push("trigger3")],
        description: "Third trigger",
      });

      await engine.emitEvent("multi_trigger", {});

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(calls).toHaveLength(3);
      expect(calls).toContain("trigger1");
      expect(calls).toContain("trigger2");
      expect(calls).toContain("trigger3");
    });
  });

  describe("Conditional Triggers", () => {
    it("should only fire triggers matching condition", async () => {
      const calls: any[] = [];

      engine.registerTrigger({
        eventType: "quality_gate",
        condition: (data) => data.allPassed === true,
        actions: [async (data) => calls.push(data)],
        description: "Deploy on pass",
      });

      await engine.emitEvent("quality_gate", { allPassed: false });
      await new Promise((resolve) => setTimeout(resolve, 100));
      expect(calls).toHaveLength(0);

      await engine.emitEvent("quality_gate", { allPassed: true });
      await new Promise((resolve) => setTimeout(resolve, 100));
      expect(calls).toHaveLength(1);
      expect(calls[0].allPassed).toBe(true);
    });

    it("should handle complex conditions", async () => {
      const calls: any[] = [];

      engine.registerTrigger({
        eventType: "cost_check",
        condition: (data) => data.cost > 100 && data.threshold === true,
        actions: [async (data) => calls.push(data)],
        description: "Alert on high cost",
      });

      // Should not fire: cost too low
      await engine.emitEvent("cost_check", { cost: 50, threshold: true });
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(calls).toHaveLength(0);

      // Should not fire: threshold not met
      await engine.emitEvent("cost_check", { cost: 150, threshold: false });
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(calls).toHaveLength(0);

      // Should fire: all conditions met
      await engine.emitEvent("cost_check", { cost: 150, threshold: true });
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(calls).toHaveLength(1);
    });

    it("should skip trigger if condition throws error", async () => {
      const calls: any[] = [];

      engine.registerTrigger({
        eventType: "error_condition",
        condition: () => {
          throw new Error("Condition error");
        },
        actions: [async (data) => calls.push(data)],
        description: "Error test",
      });

      // Should not crash, should skip trigger
      await engine.emitEvent("error_condition", { value: "test" });
      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(calls).toHaveLength(0);
    });
  });

  describe("Error Handling", () => {
    it("should handle action errors without crashing", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "error_test",
        actions: [
          async () => {
            throw new Error("Intentional error");
          },
          async () => calls.push("second_action"),
        ],
        description: "Error test",
      });

      // Should not throw
      await expect(engine.emitEvent("error_test", {})).resolves.not.toThrow();

      await new Promise((resolve) => setTimeout(resolve, 100));

      // Second action should still run
      expect(calls).toContain("second_action");
    });

    it("should handle multiple action errors", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "multi_error",
        actions: [
          async () => {
            throw new Error("Error 1");
          },
          async () => calls.push("between"),
          async () => {
            throw new Error("Error 2");
          },
          async () => calls.push("after"),
        ],
        description: "Multi-error test",
      });

      await expect(engine.emitEvent("multi_error", {})).resolves.not.toThrow();

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(calls).toEqual(["between", "after"]);
    });

    it("should handle trigger-level errors", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "trigger_error1",
        actions: [async () => calls.push("trigger1_action")],
        description: "Trigger 1",
      });

      engine.registerTrigger({
        eventType: "trigger_error1",
        condition: () => {
          throw new Error("Trigger 2 condition error");
        },
        actions: [async () => calls.push("trigger2_action")],
        description: "Trigger 2",
      });

      engine.registerTrigger({
        eventType: "trigger_error1",
        actions: [async () => calls.push("trigger3_action")],
        description: "Trigger 3",
      });

      await expect(engine.emitEvent("trigger_error1", {})).resolves.not.toThrow();

      await new Promise((resolve) => setTimeout(resolve, 100));

      // Triggers 1 and 3 should run, trigger 2 should be skipped
      expect(calls).toEqual(["trigger1_action", "trigger3_action"]);
    });
  });

  describe("Priority Handling", () => {
    it("should execute triggers in priority order", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "priority_test",
        priority: "normal",
        actions: [async () => calls.push("normal")],
        description: "Normal priority",
      });

      engine.registerTrigger({
        eventType: "priority_test",
        priority: "low",
        actions: [async () => calls.push("low")],
        description: "Low priority",
      });

      engine.registerTrigger({
        eventType: "priority_test",
        priority: "high",
        actions: [async () => calls.push("high")],
        description: "High priority",
      });

      await engine.emitEvent("priority_test", {});

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(calls).toEqual(["high", "normal", "low"]);
    });

    it("should default to normal priority", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "default_priority",
        actions: [async () => calls.push("no_priority")],
        description: "No priority specified",
      });

      engine.registerTrigger({
        eventType: "default_priority",
        priority: "high",
        actions: [async () => calls.push("high")],
        description: "High priority",
      });

      await engine.emitEvent("default_priority", {});

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(calls[0]).toBe("high");
      expect(calls[1]).toBe("no_priority");
    });
  });

  describe("Trigger Management", () => {
    it("should get all triggers", () => {
      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1",
      });

      engine.registerTrigger({
        eventType: "event2",
        actions: [async () => {}],
        description: "Trigger 2",
      });

      const triggers = engine.getTriggers();
      expect(triggers).toHaveLength(2);
    });

    it("should get triggers by event type", () => {
      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1a",
      });

      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1b",
      });

      engine.registerTrigger({
        eventType: "event2",
        actions: [async () => {}],
        description: "Trigger 2",
      });

      const event1Triggers = engine.getTriggers("event1");
      expect(event1Triggers).toHaveLength(2);

      const event2Triggers = engine.getTriggers("event2");
      expect(event2Triggers).toHaveLength(1);
    });

    it("should unregister triggers by ID", async () => {
      const trigger: EventTrigger = {
        eventType: "unregister_test",
        actions: [async () => {}],
        description: "Test trigger",
        id: "test-trigger-123",
      };

      engine.registerTrigger(trigger);
      expect(engine.getTriggers()).toHaveLength(1);

      const result = engine.unregisterTrigger("test-trigger-123");
      expect(result).toBe(true);
      expect(engine.getTriggers()).toHaveLength(0);
    });

    it("should return false when unregistering non-existent trigger", () => {
      const result = engine.unregisterTrigger("non-existent");
      expect(result).toBe(false);
    });

    it("should clear all triggers", () => {
      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1",
      });

      engine.registerTrigger({
        eventType: "event2",
        actions: [async () => {}],
        description: "Trigger 2",
      });

      expect(engine.getTriggers().length).toBeGreaterThan(0);

      engine.clearAll();
      expect(engine.getTriggers()).toHaveLength(0);
    });

    it("should clear triggers for specific event", () => {
      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1",
      });

      engine.registerTrigger({
        eventType: "event2",
        actions: [async () => {}],
        description: "Trigger 2",
      });

      const count = engine.clearEvent("event1");
      expect(count).toBe(1);
      expect(engine.getTriggers("event1")).toHaveLength(0);
      expect(engine.getTriggers("event2")).toHaveLength(1);
    });

    it("should get trigger statistics", () => {
      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1",
      });

      engine.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 2",
      });

      engine.registerTrigger({
        eventType: "event2",
        actions: [async () => {}],
        description: "Trigger 3",
      });

      const stats = engine.getStats();
      expect(stats.totalTriggers).toBe(3);
      expect(stats.triggersByEvent.event1).toBe(2);
      expect(stats.triggersByEvent.event2).toBe(1);
      expect(stats.executingCount).toBe(0);
    });

    it("should validate trigger on registration", () => {
      expect(() => {
        engine.registerTrigger({
          eventType: "",
          actions: [async () => {}],
          description: "Invalid trigger",
        });
      }).toThrow("must have a non-empty eventType");

      expect(() => {
        engine.registerTrigger({
          eventType: "valid",
          actions: [],
          description: "No actions",
        });
      }).toThrow("must have at least one action");
    });
  });

  describe("Singleton Pattern", () => {
    it("should return same instance from getTriggerEngine", () => {
      resetTriggerEngine();

      const engine1 = getTriggerEngine();
      const engine2 = getTriggerEngine();

      expect(engine1).toBe(engine2);
    });

    it("should reset singleton", () => {
      const engine1 = getTriggerEngine();
      engine1.registerTrigger({
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger",
      });

      expect(engine1.getTriggers()).toHaveLength(1);

      resetTriggerEngine();

      const engine2 = getTriggerEngine();
      expect(engine2.getTriggers()).toHaveLength(0);
      expect(engine1).not.toBe(engine2);
    });
  });

  describe("Event Handler Functions", () => {
    it("should execute quality gate passed handler", async () => {
      const data: QualityGatePassedData = {
        projectId: "test-project",
        commitSha: "abc123",
        testsPassed: true,
        allChecks: true,
      };

      await expect(handleQualityGatePassed(data)).resolves.not.toThrow();
    });

    it("should execute test failed handler", async () => {
      const data: TestFailedData = {
        projectId: "test-project",
        testName: "should calculate sum",
        errorMessage: "Expected 10 but got 5",
        failureCount: 1,
      };

      await expect(handleTestFailed(data)).resolves.not.toThrow();
    });

    it("should execute cost alert handler", async () => {
      const data: CostAlertData = {
        projectId: "test-project",
        dailyCost: 25.5,
        monthlyCost: 450.75,
        dailyLimit: 50,
        monthlyLimit: 500,
        percentOfLimit: 90.15,
        alertLevel: "warning",
      };

      await expect(handleCostAlert(data)).resolves.not.toThrow();
    });

    it("should execute agent timeout handler", async () => {
      const data: AgentTimeoutData = {
        agentId: "agent-1",
        taskId: "task-123",
        runningMs: 120000,
        timeoutMs: 60000,
      };

      await expect(handleAgentTimeout(data)).resolves.not.toThrow();
    });

    it("should execute workflow completed handler", async () => {
      const data: WorkflowCompletedData = {
        workflowId: "workflow-1",
        projectId: "project-1",
        totalCost: 5.25,
        executionTimeMs: 45000,
        agentsUsed: ["agent-1", "agent-2"],
        success: true,
      };

      await expect(handleWorkflowCompleted(data)).resolves.not.toThrow();
    });

    it("should execute build started handler", async () => {
      await expect(
        handleBuildStarted({
          buildId: "build-1",
          projectId: "project-1",
          version: "1.0.0",
          triggerSource: "webhook",
        }),
      ).resolves.not.toThrow();
    });

    it("should execute build completed handler", async () => {
      await expect(
        handleBuildCompleted({
          buildId: "build-1",
          projectId: "project-1",
          version: "1.0.0",
          success: true,
          duration: 120,
          artifactUrl: "https://example.com/artifact.zip",
        }),
      ).resolves.not.toThrow();
    });

    it("should execute deployment started handler", async () => {
      await expect(
        handleDeploymentStarted({
          deploymentId: "deploy-1",
          projectId: "project-1",
          environment: "production",
          version: "1.0.0",
          commitSha: "abc123",
        }),
      ).resolves.not.toThrow();
    });

    it("should execute security alert handler", async () => {
      await expect(
        handleSecurityAlert({
          alertId: "alert-1",
          severity: "high",
          title: "SQL Injection detected",
          description: "Unsanitized user input in database query",
          affectedComponent: "login endpoint",
        }),
      ).resolves.not.toThrow();
    });
  });

  describe("Integration Scenarios", () => {
    it("should handle quality gate workflow", async () => {
      const actions: string[] = [];

      engine.registerTrigger({
        eventType: "quality_gate_passed",
        condition: (data) => data.allChecks === true,
        actions: [
          async (data) => actions.push(`Running tests for ${data.projectId}`),
          async (data) => actions.push(`Deploying ${data.projectId}`),
        ],
        description: "Auto-deploy on quality gate pass",
      });

      const data: QualityGatePassedData = {
        projectId: "my-app",
        commitSha: "abc123",
        testsPassed: true,
        allChecks: true,
      };

      await engine.emitEvent("quality_gate_passed", data);

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(actions).toHaveLength(2);
      expect(actions[0]).toContain("my-app");
      expect(actions[1]).toContain("my-app");
    });

    it("should handle cost alert workflow", async () => {
      const alerts: any[] = [];
      const remediations: any[] = [];

      engine.registerTrigger({
        eventType: "cost_alert",
        condition: (data) => data.percentOfLimit > 85,
        actions: [
          async (data) => alerts.push(data),
          async (data) => {
            if (data.percentOfLimit > 95) {
              remediations.push(`Enabled cost-cutting mode for ${data.projectId}`);
            }
          },
        ],
        description: "Alert and remediate high costs",
        priority: "high",
      });

      // Trigger alert
      const data: CostAlertData = {
        projectId: "expensive-project",
        dailyCost: 30,
        monthlyCost: 480,
        dailyLimit: 50,
        monthlyLimit: 500,
        percentOfLimit: 96,
        alertLevel: "critical",
      };

      await engine.emitEvent("cost_alert", data);

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(alerts).toHaveLength(1);
      expect(remediations).toHaveLength(1);
    });

    it("should chain triggers across multiple events", async () => {
      const events: string[] = [];

      engine.registerTrigger({
        eventType: "build_completed",
        condition: (data) => data.success === true,
        actions: [async (data) => events.push(`Build succeeded: ${data.buildId}`)],
        description: "Track successful builds",
      });

      engine.registerTrigger({
        eventType: "build_completed",
        condition: (data) => data.success === true,
        actions: [async (data) => events.push(`Triggering deployment for ${data.buildId}`)],
        description: "Deploy on successful build",
      });

      await engine.emitEvent("build_completed", {
        buildId: "build-1",
        projectId: "project-1",
        version: "1.0.0",
        success: true,
        duration: 120,
      });

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(events).toHaveLength(2);
    });
  });

  describe("Edge Cases", () => {
    it("should handle firing event with no registered triggers", async () => {
      await expect(engine.emitEvent("non_existent_event", {})).resolves.not.toThrow();
    });

    it("should handle async action delays", async () => {
      const calls: string[] = [];

      engine.registerTrigger({
        eventType: "async_test",
        actions: [
          async () => {
            await new Promise((resolve) => setTimeout(resolve, 50));
            calls.push("action1");
          },
          async () => {
            await new Promise((resolve) => setTimeout(resolve, 30));
            calls.push("action2");
          },
        ],
        description: "Async actions",
      });

      await engine.emitEvent("async_test", {});

      await new Promise((resolve) => setTimeout(resolve, 150));

      expect(calls).toEqual(["action1", "action2"]);
    });

    it("should handle large data payloads", async () => {
      const received: any[] = [];

      engine.registerTrigger({
        eventType: "large_data",
        actions: [async (data) => received.push(Object.keys(data).length)],
        description: "Handle large payloads",
      });

      const largeData: Record<string, string> = {};
      for (let i = 0; i < 1000; i++) {
        largeData[`key_${i}`] = `value_${i}`;
      }

      await engine.emitEvent("large_data", largeData);

      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(received[0]).toBe(1000);
    });

    it("should support empty event data", async () => {
      const calls: any[] = [];

      engine.registerTrigger({
        eventType: "empty_data",
        actions: [async (data) => calls.push(data)],
        description: "Handle empty data",
      });

      await engine.emitEvent("empty_data", null);

      await new Promise((resolve) => setTimeout(resolve, 50));

      expect(calls).toHaveLength(1);
      expect(calls[0]).toBe(null);
    });

    it("should auto-assign trigger IDs", () => {
      const trigger1: EventTrigger = {
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 1",
      };

      const trigger2: EventTrigger = {
        eventType: "event1",
        actions: [async () => {}],
        description: "Trigger 2",
      };

      engine.registerTrigger(trigger1);
      engine.registerTrigger(trigger2);

      expect(trigger1.id).toBeTruthy();
      expect(trigger2.id).toBeTruthy();
      expect(trigger1.id).not.toBe(trigger2.id);
    });
  });

  describe("Memory and Performance", () => {
    it("should not leak memory on trigger unregistration", () => {
      for (let i = 0; i < 100; i++) {
        const triggerId = `trigger-${i}`;
        engine.registerTrigger({
          eventType: "test_event",
          actions: [async () => {}],
          description: "Test trigger",
          id: triggerId,
        });
      }

      expect(engine.getTriggers()).toHaveLength(100);

      for (let i = 0; i < 100; i++) {
        engine.unregisterTrigger(`trigger-${i}`);
      }

      expect(engine.getTriggers()).toHaveLength(0);
    });

    it("should handle rapid fire events", async () => {
      const calls: number[] = [];

      engine.registerTrigger({
        eventType: "rapid_fire",
        actions: [async (data) => calls.push(data.id)],
        description: "Rapid fire test",
      });

      for (let i = 0; i < 50; i++) {
        await engine.emitEvent("rapid_fire", { id: i });
      }

      await new Promise((resolve) => setTimeout(resolve, 500));

      expect(calls).toHaveLength(50);
    });
  });
});
