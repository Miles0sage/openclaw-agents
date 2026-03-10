/**
 * Team Coordinator Types
 * Interfaces for multi-agent orchestration system
 */

export enum TaskStatus {
  Pending = "pending",
  InProgress = "in_progress",
  Complete = "complete",
  Failed = "failed",
}

export interface TaskDefinition {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  assignedAgent?: string;
  result?: unknown;
  error?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
}

export interface AgentStatus {
  agentId: string;
  agentName: string;
  status: "idle" | "working" | "complete" | "failed";
  currentTaskId?: string;
  tasksCompleted: number;
  totalCost: number;
  error?: string;
}

export interface WorkerPool {
  agents: AgentStatus[];
  allTasksComplete: boolean;
  totalCost: number;
  parallelizationGain: number; // latency reduction ratio
}

export interface TaskQueueFile {
  sessionId: string;
  tasks: TaskDefinition[];
  agentStatuses: Record<string, AgentStatus>;
  metadata: {
    createdAt: string;
    updatedAt: string;
    totalCost: number;
    parallelStartTime: number;
    sequentialStartTime?: number;
  };
}
