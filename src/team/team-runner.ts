/**
 * Team Runner CLI
 * Entry point for multi-agent orchestration
 */

import type { TaskDefinition } from "./types.js";
import { createDefaultDeps } from "../cli/deps.js";
import { TaskQueue } from "./task-queue.js";
import { TeamCoordinator } from "./team-coordinator.js";

interface TeamRunOptions {
  project: string;
  task: string;
  agents?: string[];
  timeout?: number;
  verbose?: boolean;
}

/**
 * Parse CLI arguments
 */
function parseArgs(args: string[]): TeamRunOptions {
  const options: Partial<TeamRunOptions> = {};

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--project" && args[i + 1]) {
      options.project = args[++i];
    } else if (arg === "--task" && args[i + 1]) {
      options.task = args[++i];
    } else if (arg === "--agents" && args[i + 1]) {
      options.agents = args[++i].split(",");
    } else if (arg === "--timeout" && args[i + 1]) {
      options.timeout = parseInt(args[++i], 10);
    } else if (arg === "--verbose") {
      options.verbose = true;
    }
  }

  if (!options.project || !options.task) {
    throw new Error("Missing required arguments: --project and --task are required");
  }

  return options as TeamRunOptions;
}

/**
 * Format cost display
 */
function formatCost(cost: number): string {
  if (cost < 0.01) {
    return `$${(cost * 1000).toFixed(2)}m`;
  }
  return `$${cost.toFixed(4)}`;
}

/**
 * Display progress bar
 */
function displayProgress(summary: ReturnType<TaskQueue["getSummary"]>): string {
  const { total, pending, inProgress, complete, failed } = summary;
  const filledComplete = Math.floor((complete / total) * 20);
  const filledProgress = Math.floor((inProgress / total) * 20);
  const bar =
    "█".repeat(filledComplete) +
    "▌".repeat(filledProgress) +
    "░".repeat(20 - filledComplete - filledProgress);

  return `[${bar}] ${complete}/${total} tasks (${pending} pending, ${inProgress} in progress, ${failed} failed)`;
}

/**
 * Run team orchestration
 */
export async function runTeam(args: string[]): Promise<void> {
  const opts = parseArgs(args);
  const sessionId = `${opts.project}:${Date.now()}`;

  if (opts.verbose) {
    console.log(`\n🚀 Starting Team Coordinator`);
    console.log(`   Project: ${opts.project}`);
    console.log(`   Task: ${opts.task}`);
    console.log(`   Session: ${sessionId}`);
    console.log(`   Timeout: ${opts.timeout ?? 60000}ms\n`);
  }

  const deps = createDefaultDeps();

  // Define default agents (Architect, Coder, Auditor)
  const defaultAgents = [
    { id: "architect", name: "Architect Agent", model: "claude-opus-4-6" },
    { id: "coder", name: "Coder Agent", model: "claude-opus-4-6" },
    { id: "auditor", name: "Auditor Agent", model: "claude-opus-4-6" },
  ];

  const agents = opts.agents
    ? opts.agents.map((id) => ({
        id,
        name: `${id} Agent`,
        model: "claude-opus-4-6",
      }))
    : defaultAgents;

  const coordinator = new TeamCoordinator(sessionId, agents);

  // Define sample tasks for the project
  const tasks = [
    {
      title: `Analyze ${opts.project} requirements`,
      description: `Review project structure and identify ${opts.task} requirements`,
    },
    {
      title: `Implement ${opts.task} feature`,
      description: `Code and test the ${opts.task} functionality`,
    },
    {
      title: `Audit and review ${opts.task}`,
      description: `Security audit and code review of ${opts.task}`,
    },
  ];

  try {
    // Mock task executor for demonstration
    const mockExecutor = async (
      agentId: string,
      task: TaskDefinition,
    ): Promise<{ result: unknown; cost: number }> => {
      if (opts.verbose) {
        console.log(`   [${agentId}] Starting: ${task.title}`);
      }

      // Simulate work (500-2000ms)
      const workTime = Math.random() * 1500 + 500;
      await new Promise((resolve) => setTimeout(resolve, workTime));

      const cost = Math.random() * 0.05 + 0.01; // $0.01-0.06 per task

      if (opts.verbose) {
        console.log(`   [${agentId}] Completed: ${task.title} (${formatCost(cost)})`);
      }

      return {
        result: { agentId, taskTitle: task.title, completedAt: new Date().toISOString() },
        cost,
      };
    };

    // Spawn agents and execute
    const result = await coordinator.spawnAgents(tasks, mockExecutor);

    // Display summary
    console.log("\n" + "=".repeat(60));
    console.log("📊 Team Execution Summary");
    console.log("=".repeat(60));

    const summary = coordinator.getQueueSummary();
    console.log(`\n${displayProgress(summary)}`);
    console.log(`\n💰 Cost Breakdown:`);
    console.log(`   Total Cost: ${formatCost(result.totalCost)}`);
    console.log(`   Parallel Time: ${result.parallelElapsedMs.toFixed(0)}ms`);
    console.log(`   Sequential Baseline: ${result.sequentialBaselineMs.toFixed(0)}ms`);
    console.log(`   Parallelization Gain: ${result.parallelizationGain.toFixed(2)}x`);

    console.log(`\n👥 Agent Summary:`);
    const agentStatuses = coordinator.getWorkerPoolStatus().agents;
    for (const agent of agentStatuses) {
      console.log(
        `   ${agent.agentName}: ${agent.tasksCompleted} tasks, ${formatCost(agent.totalCost)}`,
      );
    }

    console.log(`\n✅ Results (${result.results.length} completed tasks):`);
    for (const res of result.results) {
      console.log(`   [${res.agentId}] ${res.task.title}: ${res.task.status}`);
    }

    // Display failed tasks if any
    const taskResults = coordinator.getTaskResults();
    const failedTasks = taskResults.filter((t) => t.status === "failed");
    if (failedTasks.length > 0) {
      console.log(`\n❌ Failed Tasks (${failedTasks.length}):`);
      for (const task of failedTasks) {
        console.log(`   ${task.title}: ${task.error}`);
      }
    }

    console.log("\n" + "=".repeat(60) + "\n");
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error(`\n❌ Team Execution Failed: ${errorMsg}\n`);
    process.exit(1);
  } finally {
    coordinator.cleanup();
  }
}

/**
 * CLI entry point
 */
if (import.meta.url === `file://${process.argv[1]}`) {
  runTeam(process.argv.slice(2)).catch((error) => {
    console.error("Fatal error:", error);
    process.exit(1);
  });
}
