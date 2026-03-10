/**
 * GET /api/agency/costs
 * Show cumulative costs for the current month or custom date range
 * Reads from local costs JSONL file (no Redis/Upstash dependency)
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import type { AgencyConfig, CostsResponse, ErrorResponse } from "../agency.types.js";
import { sendJson, getQueryParam } from "../agency-http.js";

/**
 * A single cost entry as written to the JSONL file by the Python gateway.
 * Both the "new" schema (tokens_in/tokens_out) and the legacy agency schema
 * (tokens_input/tokens_output) are tolerated.
 */
interface RawCostEntry {
  timestamp: string;
  type?: string;
  model?: string;
  agent?: string;
  project?: string;
  // New schema (Python gateway)
  tokens_in?: number;
  tokens_out?: number;
  // Legacy / agency schema
  tokens_input?: number;
  tokens_output?: number;
  cost?: number; // USD
  cost_usd?: number; // USD (legacy field name)
  metadata?: Record<string, unknown>;
  // Agency-cycle specific
  cycle_id?: string;
  project_id?: string;
  phase?: "planning" | "execution" | "review";
}

// Resolve costs JSONL file path — prefer persistent path, fall back to /tmp
function resolveCostsPath(): string {
  const persistentPath = process.env.COSTS_FILE || "./data/costs/costs.jsonl";
  if (existsSync(persistentPath)) return persistentPath;
  const tmpPath = "/tmp/openclaw_costs.jsonl";
  if (existsSync(tmpPath)) return tmpPath;
  return persistentPath; // Return the persistent path even if missing (will be handled below)
}

/**
 * Parse the JSONL cost file and return an array of raw entries.
 * Returns an empty array if the file doesn't exist or is unreadable.
 */
function loadCostEntries(filePath: string): RawCostEntry[] {
  if (!existsSync(filePath)) {
    return [];
  }

  let raw: string;
  try {
    raw = readFileSync(filePath, "utf-8");
  } catch (err) {
    console.error(`Failed to read costs file ${filePath}:`, err);
    return [];
  }

  const entries: RawCostEntry[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      entries.push(JSON.parse(trimmed) as RawCostEntry);
    } catch {
      // Skip malformed lines
    }
  }
  return entries;
}

/** Extract cost in USD from a raw entry (handles both field name variants). */
function entryCostUsd(e: RawCostEntry): number {
  return e.cost ?? e.cost_usd ?? 0;
}

/** Extract input tokens from a raw entry. */
function entryTokensIn(e: RawCostEntry): number {
  return e.tokens_in ?? e.tokens_input ?? 0;
}

/** Extract output tokens from a raw entry. */
function entryTokensOut(e: RawCostEntry): number {
  return e.tokens_out ?? e.tokens_output ?? 0;
}

export async function handleCostsRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
  url: URL,
): Promise<boolean> {
  try {
    // Parse optional date range
    const fromStr = getQueryParam(url, "from");
    const toStr = getQueryParam(url, "to");

    const today = new Date();
    const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
    const from = fromStr ? new Date(fromStr) : monthStart;
    // Set "to" to end-of-day so that today's entries are included
    const toRaw = toStr ? new Date(toStr) : today;
    const to = new Date(toRaw);
    to.setHours(23, 59, 59, 999);

    // Validate dates
    if (isNaN(from.getTime()) || isNaN(to.getTime())) {
      sendJson(res, 400, {
        error: "Invalid date format. Use YYYY-MM-DD",
        code: "INVALID_DATE",
      } as ErrorResponse);
      return true;
    }

    // Load entries from disk
    const costsPath = resolveCostsPath();
    const allEntries = loadCostEntries(costsPath);

    // Filter to requested date range
    const entries = allEntries.filter((e) => {
      if (!e.timestamp) return false;
      const ts = new Date(e.timestamp);
      return !isNaN(ts.getTime()) && ts >= from && ts <= to;
    });

    // ── Aggregate totals ──────────────────────────────────────────────────────

    let totalCost = 0;
    const byModel: Record<string, number> = {};
    const byProject: Record<string, number> = {};
    const byAgent: Record<string, number> = {};
    const byDay: Record<string, number> = {};
    // Phase buckets (used when cycle / phase data is available)
    const byPhase: Record<
      string,
      { cost: number; tokensIn: number; tokensOut: number; cycles: Set<string> }
    > = {
      planning: { cost: 0, tokensIn: 0, tokensOut: 0, cycles: new Set() },
      execution: { cost: 0, tokensIn: 0, tokensOut: 0, cycles: new Set() },
      review: { cost: 0, tokensIn: 0, tokensOut: 0, cycles: new Set() },
    };

    const cyclesSeen = new Set<string>();

    for (const e of entries) {
      const cost = entryCostUsd(e);
      const tokensIn = entryTokensIn(e);
      const tokensOut = entryTokensOut(e);

      totalCost += cost;

      // By model
      if (e.model) {
        byModel[e.model] = (byModel[e.model] ?? 0) + cost;
      }

      // By project (prefer project_id for agency entries, fall back to project)
      const projectKey = e.project_id || e.project;
      if (projectKey) {
        byProject[projectKey] = (byProject[projectKey] ?? 0) + cost;
      }

      // By agent
      const agentKey = e.agent;
      if (agentKey) {
        byAgent[agentKey] = (byAgent[agentKey] ?? 0) + cost;
      }

      // By day (YYYY-MM-DD)
      const dayKey = e.timestamp.slice(0, 10);
      byDay[dayKey] = (byDay[dayKey] ?? 0) + cost;

      // By phase
      const phase = e.phase;
      if (phase && byPhase[phase]) {
        byPhase[phase].cost += cost;
        byPhase[phase].tokensIn += tokensIn;
        byPhase[phase].tokensOut += tokensOut;
        if (e.cycle_id) byPhase[phase].cycles.add(e.cycle_id);
      }

      if (e.cycle_id) cyclesSeen.add(e.cycle_id);
    }

    // ── Budget / guardrail calculations ──────────────────────────────────────

    const monthlyCap = config.costs?.monthly_hard_cap ?? 600;
    const dailyCap = config.costs?.daily_hard_cap ?? 40;
    const perCycleCap = config.costs?.per_cycle_hard_cap ?? 8;

    const remainingBudget = Math.max(0, monthlyCap - totalCost);

    // Days remaining in month
    const lastDayOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
    const daysRemaining = lastDayOfMonth - today.getDate();

    // Projection: average daily spend × days remaining
    const daysElapsed = Math.max(1, today.getDate() - monthStart.getDate() + 1);
    const avgDailySpend = totalCost / daysElapsed;
    const projectedMonthlyTotal = totalCost + avgDailySpend * daysRemaining;

    // Count daily cap exceeded days
    let dailyMaxExceeded = 0;
    for (const dayCost of Object.values(byDay)) {
      if (dayCost > dailyCap) dailyMaxExceeded++;
    }

    // ── Build per-phase summary ───────────────────────────────────────────────

    // Determine dominant model per phase (highest spend model for that phase)
    function dominantModelForEntries(phaseLabel: "planning" | "execution" | "review"): string {
      const phaseEntries = entries.filter((e) => e.phase === phaseLabel);
      const modelCosts: Record<string, number> = {};
      for (const e of phaseEntries) {
        if (e.model) modelCosts[e.model] = (modelCosts[e.model] ?? 0) + entryCostUsd(e);
      }
      const sorted = Object.entries(modelCosts).sort((a, b) => b[1] - a[1]);
      return sorted[0]?.[0] ?? config.model_selection?.[phaseLabel] ?? "unknown";
    }

    const planningCycles = byPhase.planning.cycles.size || cyclesSeen.size;
    const executionCycles = byPhase.execution.cycles.size || cyclesSeen.size;
    const reviewCycles = byPhase.review.cycles.size || cyclesSeen.size;

    // ── Response ─────────────────────────────────────────────────────────────

    // Format project costs as "$X.XX" strings
    const byProjectFormatted: Record<string, string> = {};
    for (const [proj, cost] of Object.entries(byProject)) {
      byProjectFormatted[proj] = `$${cost.toFixed(2)}`;
    }

    const response: CostsResponse = {
      period: `${from.toISOString().split("T")[0]} to ${to.toISOString().split("T")[0]}`,
      cycles_completed: cyclesSeen.size,
      cycles_in_progress: 0, // Would require live job data — kept at 0 for now
      costs: {
        total: `$${totalCost.toFixed(2)}`,
        by_phase: {
          planning: {
            total: `$${byPhase.planning.cost.toFixed(2)}`,
            cycles: planningCycles,
            avg_per_cycle:
              planningCycles > 0
                ? `$${(byPhase.planning.cost / planningCycles).toFixed(2)}`
                : "$0.00",
            model: dominantModelForEntries("planning"),
            tokens_used: byPhase.planning.tokensIn + byPhase.planning.tokensOut,
          },
          execution: {
            total: `$${byPhase.execution.cost.toFixed(2)}`,
            cycles: executionCycles,
            avg_per_cycle:
              executionCycles > 0
                ? `$${(byPhase.execution.cost / executionCycles).toFixed(2)}`
                : "$0.00",
            model: dominantModelForEntries("execution"),
            tokens_used: byPhase.execution.tokensIn + byPhase.execution.tokensOut,
          },
          review: {
            total: `$${byPhase.review.cost.toFixed(2)}`,
            cycles: reviewCycles,
            avg_per_cycle:
              reviewCycles > 0 ? `$${(byPhase.review.cost / reviewCycles).toFixed(2)}` : "$0.00",
            model: dominantModelForEntries("review"),
            tokens_used: byPhase.review.tokensIn + byPhase.review.tokensOut,
          },
        },
        by_project: byProjectFormatted,
      },
      guardrails: {
        per_cycle_cap: `$${perCycleCap.toFixed(2)}`,
        per_cycle_max_exceeded: 0, // Would need per-cycle cost tracking to calculate accurately
        daily_cap: `$${dailyCap.toFixed(2)}`,
        daily_max_exceeded: dailyMaxExceeded,
        monthly_cap: `$${monthlyCap.toFixed(2)}`,
        remaining_budget: `$${remainingBudget.toFixed(2)}`,
      },
      projections: {
        projected_monthly_total: `$${projectedMonthlyTotal.toFixed(2)}`,
        days_remaining_in_month: daysRemaining,
        will_exceed_budget: projectedMonthlyTotal > monthlyCap,
      },
      efficiency: {
        cost_per_feature:
          cyclesSeen.size > 0 ? `$${(totalCost / cyclesSeen.size).toFixed(2)}` : "$0.00",
        prs_merged: 0, // Not tracked in cost file — would need separate PR log
        avg_pr_size: "N/A",
        test_pass_rate: "N/A",
      },
      timestamp: new Date().toISOString(),
    };

    sendJson(res, 200, response);
    return true;
  } catch (err) {
    console.error("Costs handler error:", err);
    sendJson(res, 500, {
      error: "Failed to retrieve costs",
      code: "COSTS_ERROR",
    } as ErrorResponse);
    return true;
  }
}
