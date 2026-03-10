/**
 * Team Coordinator Module
 * Multi-agent orchestration system for parallel task execution
 */

export { TeamCoordinator } from "./team-coordinator.js";
export { TaskQueue } from "./task-queue.js";
export { TaskStatus } from "./types.js";
export type { TaskDefinition, AgentStatus, WorkerPool, TaskQueueFile } from "./types.js";
export { runTeam } from "./team-runner.js";
