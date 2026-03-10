/**
 * Team Coordinator
 * Orchestrates multi-agent parallel execution
 */

import type { TaskDefinition, AgentStatus, WorkerPool } from "./types.js";
import { TaskQueue } from "./task-queue.js";
import { TaskStatus } from "./types.js";

interface AgentConfig {
  id: string;
  name: string;
  model: string;
}

export class TeamCoordinator {
  private taskQueue: TaskQueue;
  private agents: AgentConfig[];
  private sessionId: string;
  private parallelStartTime: number = 0;

  constructor(sessionId: string, agents: AgentConfig[]) {
    this.sessionId = sessionId;
    this.agents = agents;
    this.taskQueue = new TaskQueue(sessionId);
  }

  /**
   * Spawn agents and execute tasks in parallel
   * Returns results from all agents
   */
  async spawnAgents<T>(
    tasks: Array<{ title: string; description: string }>,
    taskExecutor: (agentId: string, task: TaskDefinition) => Promise<{ result: T; cost: number }>,
  ): Promise<{
    results: Array<{ agentId: string; task: TaskDefinition; result: T }>;
    totalCost: number;
    parallelElapsedMs: number;
    sequentialBaselineMs: number;
    parallelizationGain: number;
  }> {
    this.parallelStartTime = Date.now();

    // Add tasks to queue
    for (const task of tasks) {
      this.taskQueue.addTask({
        title: task.title,
        description: task.description,
        status: TaskStatus.Pending,
      });
    }

    // Spawn agents in parallel
    const agentPromises = this.agents.map((agent) => this.runAgent(agent, taskExecutor));

    // Collect results
    const results: Array<{ agentId: string; task: TaskDefinition; result: T }> = [];
    for (const result of await Promise.all(agentPromises)) {
      results.push(...result);
    }

    const parallelElapsedMs = Date.now() - this.parallelStartTime;
    const totalCost = this.taskQueue.getTotalCost();

    // Calculate baseline (sequential execution estimate)
    const sequentialBaselineMs = parallelElapsedMs * Math.max(this.agents.length, 1);
    const parallelizationGain = sequentialBaselineMs / parallelElapsedMs;

    return {
      results,
      totalCost,
      parallelElapsedMs,
      sequentialBaselineMs,
      parallelizationGain,
    };
  }

  /**
   * Run a single agent - claims and executes tasks
   */
  private async runAgent<T>(
    agent: AgentConfig,
    taskExecutor: (agentId: string, task: TaskDefinition) => Promise<{ result: T; cost: number }>,
  ): Promise<Array<{ agentId: string; task: TaskDefinition; result: T }>> {
    const results: Array<{ agentId: string; task: TaskDefinition; result: T }> = [];

    // eslint-disable-next-line no-constant-condition
    while (true) {
      // Claim next task (atomic)
      const task = this.taskQueue.claimTask(agent.id);

      if (!task) {
        // No more tasks available
        break;
      }

      try {
        // Execute task
        const { result, cost } = await taskExecutor(agent.id, task);

        // Update status
        this.taskQueue.updateStatus(task.id, TaskStatus.Complete, {
          result,
          cost,
        });

        results.push({
          agentId: agent.id,
          task,
          result,
        });
      } catch (error) {
        // Mark as failed
        const errorMsg = error instanceof Error ? error.message : String(error);
        this.taskQueue.updateStatus(task.id, TaskStatus.Failed, {
          error: errorMsg,
        });
      }
    }

    return results;
  }

  /**
   * Wait for all tasks to complete with timeout
   */
  async waitForComplete(timeoutMs: number = 60000): Promise<boolean> {
    const startTime = Date.now();

    // eslint-disable-next-line no-constant-condition
    while (true) {
      if (this.taskQueue.getAllComplete()) {
        return true;
      }

      if (Date.now() - startTime > timeoutMs) {
        return false;
      }

      // Poll every 100ms
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  /**
   * Get current worker pool status
   */
  getWorkerPoolStatus(): WorkerPool {
    const agentStatuses = Object.values(this.taskQueue.getAllAgentStatuses()) as AgentStatus[];

    const allComplete = this.taskQueue.getAllComplete();
    const totalCost = this.taskQueue.getTotalCost();
    const elapsedMs = Date.now() - this.parallelStartTime;
    const sequentialMs = elapsedMs * Math.max(this.agents.length, 1);
    const parallelizationGain = sequentialMs / Math.max(elapsedMs, 1);

    return {
      agents: agentStatuses,
      allTasksComplete: allComplete,
      totalCost,
      parallelizationGain,
    };
  }

  /**
   * Get task results
   */
  getTaskResults(): TaskDefinition[] {
    return this.taskQueue.getAllTasks();
  }

  /**
   * Get queue summary for display
   */
  getQueueSummary() {
    return this.taskQueue.getSummary();
  }

  /**
   * Clean up resources
   */
  cleanup(): void {
    this.taskQueue.cleanup();
  }
}
