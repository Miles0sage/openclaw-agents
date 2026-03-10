/**
 * Test Suite for Team Coordinator
 * Validates parallel agent execution, task queue, and race conditions
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import type { TaskDefinition } from "./types.js";
import { TaskQueue } from "./task-queue.js";
import { TeamCoordinator } from "./team-coordinator.js";
import { TaskStatus } from "./types.js";

describe("TaskQueue", () => {
  let queue: TaskQueue;
  const sessionId = `test-${Date.now()}`;

  beforeEach(() => {
    queue = new TaskQueue(sessionId);
  });

  afterEach(() => {
    queue.cleanup();
  });

  describe("Task Management", () => {
    it("should add a task to the queue", () => {
      const task = queue.addTask({
        title: "Test Task",
        description: "A test task",
        status: TaskStatus.Pending,
      });

      expect(task.id).toBeDefined();
      expect(task.title).toBe("Test Task");
      expect(task.status).toBe(TaskStatus.Pending);
      expect(task.createdAt).toBeDefined();
    });

    it("should retrieve all tasks", () => {
      queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });
      queue.addTask({
        title: "Task 2",
        description: "Second task",
        status: TaskStatus.Pending,
      });

      const tasks = queue.getAllTasks();
      expect(tasks).toHaveLength(2);
      expect(tasks[0].title).toBe("Task 1");
      expect(tasks[1].title).toBe("Task 2");
    });

    it("should filter tasks by status", () => {
      const task1 = queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });
      queue.addTask({
        title: "Task 2",
        description: "Second task",
        status: TaskStatus.Pending,
      });

      queue.updateStatus(task1.id, TaskStatus.Complete);

      const pending = queue.getTasksByStatus(TaskStatus.Pending);
      const complete = queue.getTasksByStatus(TaskStatus.Complete);

      expect(pending).toHaveLength(1);
      expect(complete).toHaveLength(1);
    });
  });

  describe("Atomic Task Claiming", () => {
    it("should claim a pending task atomically", () => {
      queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });

      const claimed = queue.claimTask("agent-1");

      expect(claimed).toBeDefined();
      expect(claimed?.status).toBe(TaskStatus.InProgress);
      expect(claimed?.assignedAgent).toBe("agent-1");
      expect(claimed?.startedAt).toBeDefined();
    });

    it("should not claim the same task twice", () => {
      queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });

      const claimed1 = queue.claimTask("agent-1");
      const claimed2 = queue.claimTask("agent-2");

      expect(claimed1).toBeDefined();
      expect(claimed2).toBeNull();
      expect(claimed1?.assignedAgent).toBe("agent-1");
    });

    it("should return null when no pending tasks", () => {
      const claimed = queue.claimTask("agent-1");
      expect(claimed).toBeNull();
    });

    it("should handle concurrent claim attempts (race condition)", () => {
      queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });

      // Simulate concurrent claims
      const claims = [
        queue.claimTask("agent-1"),
        queue.claimTask("agent-2"),
        queue.claimTask("agent-3"),
      ];

      // Only first should succeed
      const successfulClaim = claims.filter((c) => c !== null);
      expect(successfulClaim).toHaveLength(1);
      expect(successfulClaim[0]?.assignedAgent).toBe("agent-1");
    });
  });

  describe("Status Updates", () => {
    it("should update task status and result", () => {
      const task = queue.addTask({
        title: "Test Task",
        description: "A test task",
        status: TaskStatus.Pending,
      });

      queue.updateStatus(task.id, TaskStatus.Complete, {
        result: { success: true },
      });

      const updated = queue.getAllTasks().find((t) => t.id === task.id);
      expect(updated?.status).toBe(TaskStatus.Complete);
      expect(updated?.result).toEqual({ success: true });
      expect(updated?.completedAt).toBeDefined();
    });

    it("should update task with error", () => {
      const task = queue.addTask({
        title: "Test Task",
        description: "A test task",
        status: TaskStatus.Pending,
      });

      queue.updateStatus(task.id, TaskStatus.Failed, {
        error: "Test error",
      });

      const updated = queue.getAllTasks().find((t) => t.id === task.id);
      expect(updated?.status).toBe(TaskStatus.Failed);
      expect(updated?.error).toBe("Test error");
    });

    it("should track cost updates", () => {
      const task = queue.addTask({
        title: "Test Task",
        description: "A test task",
        status: TaskStatus.Pending,
      });

      queue.claimTask("agent-1");
      queue.updateStatus(task.id, TaskStatus.Complete, { cost: 0.05 });

      expect(queue.getTotalCost()).toBe(0.05);
    });
  });

  describe("Agent Status Tracking", () => {
    it("should track agent status on task claim", () => {
      queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });

      queue.claimTask("agent-1");

      const agentStatus = queue.getAgentStatus("agent-1");
      expect(agentStatus).toBeDefined();
      expect(agentStatus?.status).toBe("working");
      expect(agentStatus?.tasksCompleted).toBe(0);
    });

    it("should increment task completion count", () => {
      const task = queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });

      queue.claimTask("agent-1");
      queue.updateStatus(task.id, TaskStatus.Complete);

      const agentStatus = queue.getAgentStatus("agent-1");
      expect(agentStatus?.tasksCompleted).toBe(1);
      expect(agentStatus?.status).toBe("idle");
    });

    it("should accumulate cost across tasks", () => {
      const task1 = queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });
      const task2 = queue.addTask({
        title: "Task 2",
        description: "Second task",
        status: TaskStatus.Pending,
      });

      queue.claimTask("agent-1");
      queue.updateStatus(task1.id, TaskStatus.Complete, { cost: 0.03 });

      queue.claimTask("agent-1");
      queue.updateStatus(task2.id, TaskStatus.Complete, { cost: 0.02 });

      const agentStatus = queue.getAgentStatus("agent-1");
      expect(agentStatus?.totalCost).toBe(0.05);
      expect(queue.getTotalCost()).toBe(0.05);
    });
  });

  describe("Queue Summary", () => {
    it("should provide accurate summary", () => {
      queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });
      queue.addTask({
        title: "Task 2",
        description: "Second task",
        status: TaskStatus.Pending,
      });

      const summary = queue.getSummary();
      expect(summary.total).toBe(2);
      expect(summary.pending).toBe(2);
      expect(summary.inProgress).toBe(0);
      expect(summary.complete).toBe(0);
      expect(summary.failed).toBe(0);
    });

    it("should check all complete status", () => {
      const task1 = queue.addTask({
        title: "Task 1",
        description: "First task",
        status: TaskStatus.Pending,
      });

      expect(queue.getAllComplete()).toBe(false);

      queue.updateStatus(task1.id, TaskStatus.Complete);

      expect(queue.getAllComplete()).toBe(true);
    });
  });
});

describe("TeamCoordinator", () => {
  const sessionId = `coordinator-${Date.now()}`;
  let coordinator: TeamCoordinator;

  const agents = [
    { id: "agent-1", name: "Agent 1", model: "claude-opus-4-6" },
    { id: "agent-2", name: "Agent 2", model: "claude-opus-4-6" },
    { id: "agent-3", name: "Agent 3", model: "claude-opus-4-6" },
  ];

  beforeEach(() => {
    coordinator = new TeamCoordinator(sessionId, agents);
  });

  afterEach(() => {
    coordinator.cleanup();
  });

  describe("Parallel Agent Spawning", () => {
    it("should spawn multiple agents in parallel", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
        { title: "Task 3", description: "Third task" },
      ];

      const mockExecutor = async (
        agentId: string,
        task: TaskDefinition,
      ): Promise<{ result: unknown; cost: number }> => {
        await new Promise((resolve) => setTimeout(resolve, 100));
        return {
          result: { agentId, taskTitle: task.title },
          cost: 0.01,
        };
      };

      const result = await coordinator.spawnAgents(tasks, mockExecutor);

      expect(result.results).toHaveLength(3);
      expect(result.totalCost).toBeGreaterThan(0.02);
      // With parallel execution, should be faster than sequential
      expect(result.parallelizationGain).toBeGreaterThan(1);
    });

    it("should distribute tasks across agents", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
        { title: "Task 3", description: "Third task" },
      ];

      const agentTasks: Record<string, number> = {};

      const mockExecutor = async (
        agentId: string,
        task: TaskDefinition,
      ): Promise<{ result: unknown; cost: number }> => {
        agentTasks[agentId] = (agentTasks[agentId] ?? 0) + 1;
        return { result: { agentId }, cost: 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      // Each agent should have claimed at least one task
      expect(Object.keys(agentTasks).length).toBeGreaterThan(0);
      expect(Object.values(agentTasks).reduce((a, b) => a + b, 0)).toBe(3);
    });

    it("should handle task execution failures", async () => {
      const tasks = [
        { title: "Task 1 (will fail)", description: "First task" },
        { title: "Task 2 (will fail)", description: "Second task" },
      ];

      const mockExecutor = async (
        agentId: string,
        task: TaskDefinition,
      ): Promise<{ result: unknown; cost: number }> => {
        if (task.title.includes("fail")) {
          throw new Error("Intentional failure");
        }
        return { result: { agentId }, cost: 0.01 };
      };

      const result = await coordinator.spawnAgents(tasks, mockExecutor);

      expect(result.results).toHaveLength(0); // Both tasks failed
      const taskResults = coordinator.getTaskResults();
      const failedTasks = taskResults.filter((t) => t.status === "failed");
      expect(failedTasks).toHaveLength(2);
      expect(failedTasks[0]?.error).toBe("Intentional failure");
    });

    it("should calculate parallelization gain correctly", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
        { title: "Task 3", description: "Third task" },
      ];

      const mockExecutor = async (): Promise<{ result: unknown; cost: number }> => {
        await new Promise((resolve) => setTimeout(resolve, 200));
        return { result: {}, cost: 0.01 };
      };

      const result = await coordinator.spawnAgents(tasks, mockExecutor);

      // With 3 agents and 3 tasks, should see significant parallelization
      expect(result.parallelizationGain).toBeGreaterThan(1.5);
      expect(result.parallelElapsedMs).toBeLessThan(result.sequentialBaselineMs);
    });
  });

  describe("Worker Pool Status", () => {
    it("should track worker pool status", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
      ];

      const mockExecutor = async (): Promise<{ result: unknown; cost: number }> => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return { result: {}, cost: 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      const status = coordinator.getWorkerPoolStatus();
      expect(status.agents.length).toBeGreaterThan(0);
      expect(status.allTasksComplete).toBe(true);
      expect(status.totalCost).toBeGreaterThan(0);
      expect(status.parallelizationGain).toBeGreaterThan(1);
    });

    it("should track individual agent costs", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
      ];

      const mockExecutor = async (agentId: string): Promise<{ result: unknown; cost: number }> => {
        const costs: Record<string, number> = {
          "agent-1": 0.02,
          "agent-2": 0.03,
          "agent-3": 0.01,
        };
        return { result: { agentId }, cost: costs[agentId] ?? 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      const status = coordinator.getWorkerPoolStatus();
      const costSum = status.agents.reduce((sum, a) => sum + a.totalCost, 0);
      expect(costSum).toBeGreaterThan(0);
    });
  });

  describe("Queue Management", () => {
    it("should retrieve queue summary", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
      ];

      const mockExecutor = async (): Promise<{ result: unknown; cost: number }> => {
        return { result: {}, cost: 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      const summary = coordinator.getQueueSummary();
      expect(summary.total).toBe(2);
      expect(summary.complete).toBe(2);
      expect(summary.pending).toBe(0);
    });

    it("should retrieve task results", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
      ];

      const mockExecutor = async (agentId: string): Promise<{ result: unknown; cost: number }> => {
        return { result: { agentId }, cost: 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      const results = coordinator.getTaskResults();
      expect(results).toHaveLength(2);
      expect(results.every((r) => r.status === "complete")).toBe(true);
    });
  });

  describe("Race Conditions", () => {
    it("should handle concurrent task claims without duplicates", async () => {
      // Create fewer tasks than agents
      const tasks = [{ title: "Only Task", description: "Single task" }];

      const claimedBy: string[] = [];

      const mockExecutor = async (
        agentId: string,
        task: TaskDefinition,
      ): Promise<{ result: unknown; cost: number }> => {
        claimedBy.push(agentId);
        return { result: {}, cost: 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      // Task should only be claimed by one agent
      expect(claimedBy).toHaveLength(1);
    });

    it("should prevent race condition with status updates", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
      ];

      let updateCount = 0;

      const mockExecutor = async (
        agentId: string,
        task: TaskDefinition,
      ): Promise<{ result: unknown; cost: number }> => {
        updateCount++;
        // Simulate concurrent update scenario
        await new Promise((resolve) => setTimeout(resolve, 10));
        return { result: {}, cost: 0.01 };
      };

      await coordinator.spawnAgents(tasks, mockExecutor);

      const summary = coordinator.getQueueSummary();
      expect(summary.complete).toBe(2);
      expect(updateCount).toBe(2);
    });
  });

  describe("Cost Tracking", () => {
    it("should accumulate costs correctly", async () => {
      const tasks = [
        { title: "Task 1", description: "First task" },
        { title: "Task 2", description: "Second task" },
        { title: "Task 3", description: "Third task" },
      ];

      const mockExecutor = async (): Promise<{ result: unknown; cost: number }> => {
        return { result: {}, cost: 0.02 };
      };

      const result = await coordinator.spawnAgents(tasks, mockExecutor);

      expect(result.totalCost).toBe(0.06);
    });

    it("should handle zero-cost tasks", async () => {
      const tasks = [{ title: "Task 1", description: "First task" }];

      const mockExecutor = async (): Promise<{ result: unknown; cost: number }> => {
        return { result: {}, cost: 0 };
      };

      const result = await coordinator.spawnAgents(tasks, mockExecutor);

      expect(result.totalCost).toBe(0);
    });
  });
});
