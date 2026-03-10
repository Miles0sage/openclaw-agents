/**
 * Cost Tracker Module
 * Tracks API costs, logs to JSONL, and aggregates metrics
 * Supports Claude API pricing (Haiku, Sonnet, Opus)
 */

import * as fs from "fs";
import * as path from "path";

/**
 * Cost entry logged for each API call
 */
export interface CostTracker {
  project: string;
  agent: string;
  model: string;
  tokens_input: number;
  tokens_output: number;
  cost: number;
  timestamp: string;
}

/**
 * Aggregated cost metrics
 */
export interface CostMetrics {
  total_cost: number;
  by_project: Record<string, number>;
  by_model: Record<string, number>;
  by_agent: Record<string, number>;
  entries_count: number;
  timestamp_range: {
    first: string;
    last: string;
  };
}

/**
 * Pricing constants (Feb 2026 Claude API rates)
 * Input cost per million tokens, Output cost per million tokens
 */
const PRICING = {
  "claude-3-5-haiku-20241022": {
    input: 0.8, // $0.80 per million input tokens
    output: 4.0, // $4.00 per million output tokens
  },
  "claude-3-5-sonnet-20241022": {
    input: 3.0, // $3.00 per million input tokens
    output: 15.0, // $15.00 per million output tokens
  },
  "claude-opus-4-6": {
    input: 15.0, // $15.00 per million input tokens
    output: 75.0, // $75.00 per million output tokens
  },
  // Aliases for common references
  haiku: { input: 0.8, output: 4.0 },
  sonnet: { input: 3.0, output: 15.0 },
  opus: { input: 15.0, output: 75.0 },
};

/**
 * Get pricing for a model
 */
export function getPricing(model: string): { input: number; output: number } | null {
  return PRICING[model as keyof typeof PRICING] || null;
}

/**
 * Calculate cost for tokens
 */
export function calculateCost(model: string, tokens_input: number, tokens_output: number): number {
  const pricing = getPricing(model);
  if (!pricing) {
    console.warn(`Unknown model: ${model}, defaulting to Sonnet pricing`);
    return (tokens_input * PRICING.sonnet.input + tokens_output * PRICING.sonnet.output) / 1000000;
  }

  return (tokens_input * pricing.input + tokens_output * pricing.output) / 1000000;
}

/**
 * Get default cost log file path
 */
function getCostLogPath(): string {
  return process.env.OPENCLAW_COST_LOG || "/tmp/openclaw_costs.jsonl";
}

/**
 * Log a cost event to JSONL file (append-only)
 */
export async function logCostEvent(event: CostTracker): Promise<void> {
  const logPath = getCostLogPath();

  try {
    // Ensure directory exists
    const dir = path.dirname(logPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Append to JSONL (newline-delimited JSON)
    const line = JSON.stringify(event) + "\n";
    fs.appendFileSync(logPath, line, "utf-8");
  } catch (error) {
    console.error(`Failed to log cost event: ${error}`);
  }
}

/**
 * Read and parse JSONL cost log
 */
function readCostLog(): CostTracker[] {
  const logPath = getCostLogPath();

  if (!fs.existsSync(logPath)) {
    return [];
  }

  try {
    const content = fs.readFileSync(logPath, "utf-8");
    const lines = content.split("\n").filter((line) => line.trim());

    return lines
      .map((line) => {
        try {
          return JSON.parse(line) as CostTracker;
        } catch {
          console.warn(`Failed to parse cost log line: ${line}`);
          return null;
        }
      })
      .filter((entry) => entry !== null) as CostTracker[];
  } catch (error) {
    console.error(`Failed to read cost log: ${error}`);
    return [];
  }
}

/**
 * Get cost metrics aggregated from log
 */
export function getCostMetrics(timeWindow?: string): CostMetrics {
  const entries = readCostLog();

  if (entries.length === 0) {
    return {
      total_cost: 0,
      by_project: {},
      by_model: {},
      by_agent: {},
      entries_count: 0,
      timestamp_range: { first: "", last: "" },
    };
  }

  // Filter by time window if provided (e.g., "24h", "7d", "30d")
  let filtered = entries;
  if (timeWindow) {
    const now = new Date();
    const windowMs = parseTimeWindow(timeWindow);
    const cutoff = new Date(now.getTime() - windowMs);

    filtered = entries.filter((e) => new Date(e.timestamp) >= cutoff);
  }

  // Aggregate metrics
  const metrics: CostMetrics = {
    total_cost: 0,
    by_project: {},
    by_model: {},
    by_agent: {},
    entries_count: filtered.length,
    timestamp_range: {
      first: filtered.length > 0 ? filtered[0].timestamp : "",
      last: filtered.length > 0 ? filtered[filtered.length - 1].timestamp : "",
    },
  };

  for (const entry of filtered) {
    metrics.total_cost += entry.cost;
    metrics.by_project[entry.project] = (metrics.by_project[entry.project] || 0) + entry.cost;
    metrics.by_model[entry.model] = (metrics.by_model[entry.model] || 0) + entry.cost;
    metrics.by_agent[entry.agent] = (metrics.by_agent[entry.agent] || 0) + entry.cost;
  }

  return metrics;
}

/**
 * Parse time window string to milliseconds
 */
function parseTimeWindow(window: string): number {
  const match = window.match(/^(\d+)([hdm])$/);
  if (!match) {
    console.warn(`Invalid time window: ${window}, defaulting to 24h`);
    return 24 * 60 * 60 * 1000;
  }

  const value = parseInt(match[1], 10);
  const unit = match[2];

  switch (unit) {
    case "h":
      return value * 60 * 60 * 1000;
    case "d":
      return value * 24 * 60 * 60 * 1000;
    case "m":
      return value * 60 * 1000;
    default:
      return 24 * 60 * 60 * 1000;
  }
}

/**
 * Clear all cost data (for testing)
 */
export async function clearCostLog(): Promise<void> {
  const logPath = getCostLogPath();

  try {
    if (fs.existsSync(logPath)) {
      fs.unlinkSync(logPath);
      console.log("Cost log cleared");
    }
  } catch (error) {
    console.error(`Failed to clear cost log: ${error}`);
  }
}

/**
 * Get cost summary for debugging
 */
export function getCostSummary(): string {
  const metrics = getCostMetrics();
  const summary: string[] = [
    "=== Cost Summary ===",
    `Total Cost: $${metrics.total_cost.toFixed(4)}`,
    `Entries: ${metrics.entries_count}`,
    "",
    "By Project:",
    ...Object.entries(metrics.by_project).map(
      ([project, cost]) => `  ${project}: $${cost.toFixed(4)}`,
    ),
    "",
    "By Model:",
    ...Object.entries(metrics.by_model).map(([model, cost]) => `  ${model}: $${cost.toFixed(4)}`),
    "",
    "By Agent:",
    ...Object.entries(metrics.by_agent).map(([agent, cost]) => `  ${agent}: $${cost.toFixed(4)}`),
  ];

  return summary.join("\n");
}
