/**
 * Task Queue with File-Based Persistence
 * Manages task state with atomic file operations
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { TaskDefinition, AgentStatus, TaskQueueFile } from "./types.js";
import { TaskStatus } from "./types.js";

export class TaskQueue {
  private sessionId: string;
  private queuePath: string;
  private lockPath: string;

  constructor(sessionId: string) {
    this.sessionId = sessionId;
    this.queuePath = path.join("/tmp", `team_tasks_${sessionId}.json`);
    this.lockPath = path.join("/tmp", `team_tasks_${sessionId}.lock`);
    this.ensureQueueExists();
  }

  /**
   * Ensure queue file exists with initial structure
   */
  private ensureQueueExists(): void {
    if (!fs.existsSync(this.queuePath)) {
      const initialQueue: TaskQueueFile = {
        sessionId: this.sessionId,
        tasks: [],
        agentStatuses: {},
        metadata: {
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          totalCost: 0,
          parallelStartTime: Date.now(),
        },
      };
      fs.writeFileSync(this.queuePath, JSON.stringify(initialQueue, null, 2));
    }
  }

  /**
   * Simple file-based locking to prevent race conditions
   */
  private acquireLock(timeoutMs: number = 5000): void {
    const startTime = Date.now();
    while (fs.existsSync(this.lockPath)) {
      if (Date.now() - startTime > timeoutMs) {
        throw new Error(`Lock timeout: ${this.lockPath}`);
      }
      // Busy-wait with small delay
      const buffer = Buffer.alloc(1);
      // eslint-disable-next-line no-constant-condition
      while (true) {
        // Sleep 10ms
        if (Date.now() - startTime > timeoutMs) break;
      }
    }
    // Create lock file
    fs.writeFileSync(this.lockPath, process.pid.toString());
  }

  /**
   * Release lock
   */
  private releaseLock(): void {
    if (fs.existsSync(this.lockPath)) {
      fs.unlinkSync(this.lockPath);
    }
  }

  /**
   * Read queue from disk
   */
  private readQueue(): TaskQueueFile {
    const content = fs.readFileSync(this.queuePath, "utf-8");
    return JSON.parse(content) as TaskQueueFile;
  }

  /**
   * Write queue to disk (with lock)
   */
  private writeQueue(queue: TaskQueueFile): void {
    queue.metadata.updatedAt = new Date().toISOString();
    const tempPath = `${this.queuePath}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(queue, null, 2));
    // Atomic rename
    fs.renameSync(tempPath, this.queuePath);
  }

  /**
   * Add a new task to the queue
   */
  addTask(task: Omit<TaskDefinition, "id" | "createdAt">): TaskDefinition {
    this.acquireLock();
    try {
      const queue = this.readQueue();
      const taskDef: TaskDefinition = {
        ...task,
        id: crypto.randomUUID(),
        createdAt: new Date().toISOString(),
      };
      queue.tasks.push(taskDef);
      this.writeQueue(queue);
      return taskDef;
    } finally {
      this.releaseLock();
    }
  }

  /**
   * Claim a task (atomic) - prevents race conditions
   * Returns the claimed task or null if none available
   */
  claimTask(agentId: string): TaskDefinition | null {
    this.acquireLock();
    try {
      const queue = this.readQueue();
      const taskIndex = queue.tasks.findIndex((t) => t.status === "pending");

      if (taskIndex === -1) {
        return null;
      }

      const task = queue.tasks[taskIndex];
      task.status = TaskStatus.InProgress;
      task.assignedAgent = agentId;
      task.startedAt = new Date().toISOString();

      // Update agent status
      if (!queue.agentStatuses[agentId]) {
        queue.agentStatuses[agentId] = {
          agentId,
          agentName: agentId,
          status: "working",
          currentTaskId: task.id,
          tasksCompleted: 0,
          totalCost: 0,
        };
      } else {
        queue.agentStatuses[agentId].currentTaskId = task.id;
        queue.agentStatuses[agentId].status = "working";
      }

      this.writeQueue(queue);
      return task;
    } finally {
      this.releaseLock();
    }
  }

  /**
   * Update task status and result
   */
  updateStatus(
    taskId: string,
    status: TaskStatus,
    opts?: { result?: unknown; error?: string; cost?: number },
  ): void {
    this.acquireLock();
    try {
      const queue = this.readQueue();
      const task = queue.tasks.find((t) => t.id === taskId);

      if (!task) {
        throw new Error(`Task not found: ${taskId}`);
      }

      task.status = status;
      if (opts?.result !== undefined) {
        task.result = opts.result;
      }
      if (opts?.error !== undefined) {
        task.error = opts.error;
      }
      if (status === TaskStatus.Complete || status === TaskStatus.Failed) {
        task.completedAt = new Date().toISOString();
      }

      // Update agent status
      if (task.assignedAgent) {
        const agentStatus = queue.agentStatuses[task.assignedAgent];
        if (agentStatus) {
          if (status === TaskStatus.Complete) {
            agentStatus.tasksCompleted += 1;
            agentStatus.status = "idle";
          } else if (status === TaskStatus.Failed) {
            agentStatus.status = "failed";
            agentStatus.error = opts?.error;
          }
          if (opts?.cost !== undefined) {
            agentStatus.totalCost += opts.cost;
            queue.metadata.totalCost += opts.cost;
          }
        }
      }

      this.writeQueue(queue);
    } finally {
      this.releaseLock();
    }
  }

  /**
   * Get all tasks
   */
  getAllTasks(): TaskDefinition[] {
    return this.readQueue().tasks;
  }

  /**
   * Check if all tasks are complete
   */
  getAllComplete(): boolean {
    const queue = this.readQueue();
    return queue.tasks.every(
      (t) => t.status === TaskStatus.Complete || t.status === TaskStatus.Failed,
    );
  }

  /**
   * Get tasks by status
   */
  getTasksByStatus(status: TaskStatus): TaskDefinition[] {
    return this.readQueue().tasks.filter((t) => t.status === status);
  }

  /**
   * Get agent status
   */
  getAgentStatus(agentId: string): AgentStatus | null {
    const queue = this.readQueue();
    return queue.agentStatuses[agentId] ?? null;
  }

  /**
   * Get all agent statuses
   */
  getAllAgentStatuses(): Record<string, AgentStatus> {
    return this.readQueue().agentStatuses;
  }

  /**
   * Get total cost for session
   */
  getTotalCost(): number {
    return this.readQueue().metadata.totalCost;
  }

  /**
   * Get queue summary
   */
  getSummary() {
    const queue = this.readQueue();
    return {
      total: queue.tasks.length,
      pending: queue.tasks.filter((t) => t.status === TaskStatus.Pending).length,
      inProgress: queue.tasks.filter((t) => t.status === TaskStatus.InProgress).length,
      complete: queue.tasks.filter((t) => t.status === TaskStatus.Complete).length,
      failed: queue.tasks.filter((t) => t.status === TaskStatus.Failed).length,
      totalCost: queue.metadata.totalCost,
      agents: Object.values(queue.agentStatuses).length,
    };
  }

  /**
   * Clean up queue file
   */
  cleanup(): void {
    if (fs.existsSync(this.queuePath)) {
      fs.unlinkSync(this.queuePath);
    }
    if (fs.existsSync(this.lockPath)) {
      fs.unlinkSync(this.lockPath);
    }
  }
}
