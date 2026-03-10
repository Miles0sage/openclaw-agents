/**
 * Agency Cost Tracker
 * Tracks costs in Redis (via Upstash REST API or native Redis)
 */

import type { CostEntry } from "./agency.types.js";

interface RedisClient {
  lpush(key: string, ...values: string[]): Promise<number>;
  lrange(key: string, start: number, stop: number): Promise<string[]>;
  incrbyfloat(key: string, increment: number): Promise<number>;
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: { ex?: number }): Promise<string>;
  expire(key: string, seconds: number): Promise<number>;
  del(...keys: string[]): Promise<number>;
}

let redisClient: RedisClient | null = null;

/**
 * Initialize the Redis client (provide your own Redis or Upstash client)
 */
export function initCostTracker(client: RedisClient): void {
  redisClient = client;
}

/**
 * Get the Redis client
 */
function getClient(): RedisClient {
  if (!redisClient) {
    throw new Error("Cost tracker not initialized. Call initCostTracker() first.");
  }
  return redisClient;
}

/**
 * Record a cost entry in Redis
 */
export async function recordCost(entry: CostEntry): Promise<void> {
  const client = getClient();

  // Store in list for detailed history
  const key = `agency:costs:${entry.cycle_id}`;
  await client.lpush(key, JSON.stringify(entry));

  // Track aggregate costs by phase
  const phaseKey = `agency:costs:by_phase:${entry.phase}`;
  await client.incrbyfloat(phaseKey, entry.cost_usd);

  // Track aggregate costs by project
  const projectKey = `agency:costs:by_project:${entry.project_id}`;
  await client.incrbyfloat(projectKey, entry.cost_usd);

  // Track total for cycle
  const cycleKey = `agency:costs:cycles:${entry.cycle_id}:total`;
  await client.incrbyfloat(cycleKey, entry.cost_usd);

  // Expire after 30 days
  await client.expire(key, 86400 * 30);
  await client.expire(cycleKey, 86400 * 30);
}

/**
 * Get all costs for a specific cycle
 */
export async function getCycleCosts(cycle_id: string): Promise<CostEntry[]> {
  const client = getClient();
  const key = `agency:costs:${cycle_id}`;

  try {
    const entries = await client.lrange(key, 0, -1);
    return entries.map((entry) => JSON.parse(entry) as CostEntry);
  } catch (err) {
    console.error("Failed to get cycle costs:", err);
    return [];
  }
}

/**
 * Get total cost for a cycle
 */
export async function getCycleTotalCost(cycle_id: string): Promise<number> {
  const client = getClient();
  const key = `agency:costs:cycles:${cycle_id}:total`;

  try {
    const result = await client.get(key);
    return result ? parseFloat(result) : 0;
  } catch (err) {
    console.error("Failed to get cycle total cost:", err);
    return 0;
  }
}

/**
 * Get costs aggregated by phase for a date range
 */
export async function getCostsByPhase(from: Date, to: Date): Promise<Record<string, number>> {
  const client = getClient();

  try {
    const phases = ["planning", "execution", "review"] as const;
    const result: Record<string, number> = {};

    for (const phase of phases) {
      const key = `agency:costs:by_phase:${phase}`;
      const value = await client.get(key);
      result[phase] = value ? parseFloat(value) : 0;
    }

    return result;
  } catch (err) {
    console.error("Failed to get costs by phase:", err);
    return { planning: 0, execution: 0, review: 0 };
  }
}

/**
 * Get costs aggregated by project for a date range
 */
export async function getCostsByProject(
  from: Date,
  to: Date,
  config: { projects: Array<{ id: string }> },
): Promise<Record<string, number>> {
  const client = getClient();

  try {
    const result: Record<string, number> = {};

    for (const project of config.projects) {
      const key = `agency:costs:by_project:${project.id}`;
      const value = await client.get(key);
      result[project.id] = value ? parseFloat(value) : 0;
    }

    return result;
  } catch (err) {
    console.error("Failed to get costs by project:", err);
    return {};
  }
}

/**
 * Check if we've exceeded daily hard cap
 */
export async function checkDailyHardCap(
  dailyHardCap: number,
  today: Date,
): Promise<{ exceeded: boolean; current: number }> {
  const client = getClient();
  const dateStr = today.toISOString().split("T")[0];
  const key = `agency:costs:daily:${dateStr}:total`;

  try {
    const value = await client.get(key);
    const current = value ? parseFloat(value) : 0;
    return {
      exceeded: current >= dailyHardCap,
      current,
    };
  } catch (err) {
    console.error("Failed to check daily hard cap:", err);
    return { exceeded: false, current: 0 };
  }
}

/**
 * Record daily cost (for tracking daily hard cap)
 */
export async function recordDailyCost(amount: number, date: Date): Promise<void> {
  const client = getClient();
  const dateStr = date.toISOString().split("T")[0];
  const key = `agency:costs:daily:${dateStr}:total`;

  try {
    await client.incrbyfloat(key, amount);
    // Expire after 2 days
    await client.expire(key, 86400 * 2);
  } catch (err) {
    console.error("Failed to record daily cost:", err);
  }
}

/**
 * Get monthly cost projection
 */
export async function getMonthlyProjection(monthlyHardCap: number): Promise<{
  projected_total: number;
  will_exceed: boolean;
  days_elapsed: number;
  days_remaining: number;
}> {
  const client = getClient();
  const today = new Date();
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
  const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0);

  const daysElapsed = Math.ceil((today.getTime() - monthStart.getTime()) / (1000 * 60 * 60 * 24));
  const daysInMonth = monthEnd.getDate();
  const daysRemaining = daysInMonth - daysElapsed;

  try {
    const monthKey = `agency:costs:monthly:${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}:total`;
    const value = await client.get(monthKey);
    const monthlyTotal = value ? parseFloat(value) : 0;

    const avgPerDay = monthlyTotal / Math.max(daysElapsed, 1);
    const projected = monthlyTotal + avgPerDay * daysRemaining;

    return {
      projected_total: Math.round(projected * 100) / 100,
      will_exceed: projected >= monthlyHardCap,
      days_elapsed: daysElapsed,
      days_remaining: daysRemaining,
    };
  } catch (err) {
    console.error("Failed to calculate monthly projection:", err);
    return {
      projected_total: 0,
      will_exceed: false,
      days_elapsed: daysElapsed,
      days_remaining: daysRemaining,
    };
  }
}

/**
 * Clear all cost data (for testing)
 */
export async function clearAllCosts(): Promise<void> {
  const client = getClient();

  try {
    // Delete all agency cost keys
    const patterns = [
      "agency:costs:*",
      "agency:costs:by_phase:*",
      "agency:costs:by_project:*",
      "agency:costs:daily:*",
      "agency:costs:monthly:*",
    ];

    for (const pattern of patterns) {
      // Note: This is a simplified implementation
      // In production, use Redis SCAN for pagination
      // For now, we'll just return a warning
      console.warn(`Cost clearing not fully implemented for pattern: ${pattern}`);
    }
  } catch (err) {
    console.error("Failed to clear costs:", err);
  }
}
