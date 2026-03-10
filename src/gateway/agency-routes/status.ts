/**
 * GET /api/agency/status
 * Check the status of a running or completed cycle, or return a summary of all jobs.
 * Reads from local jobs JSONL file and optionally queries the Python gateway.
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import type {
  AgencyConfig,
  StatusResponse,
  ErrorResponse,
  ProjectStatus,
} from "../agency.types.js";
import { sendJson, getQueryParam } from "../agency-http.js";

/** Shape of a job record as stored in jobs.jsonl */
interface JobRecord {
  id: string;
  project?: string;
  project_id?: string;
  cycle_id?: string;
  task?: string;
  priority?: string;
  status: string; // "pending" | "running" | "done" | "failed" | "pr_ready" | ...
  created_at?: string;
  completed_at?: string | null;
  pr_url?: string | null;
  branch_name?: string | null;
  approved_by?: string | null;
  error?: string | null;
}

// Resolve jobs JSONL file path — prefer persistent, fall back to /tmp
function resolveJobsPath(): string {
  const persistentPath = process.env.JOBS_FILE || "./data/jobs/jobs.jsonl";
  if (existsSync(persistentPath)) return persistentPath;
  const tmpPath = "/tmp/openclaw_jobs/jobs.jsonl";
  if (existsSync(tmpPath)) return tmpPath;
  return persistentPath;
}

/** Parse the JSONL jobs file. Returns empty array if file is absent or unreadable. */
function loadJobsFromFile(filePath: string): JobRecord[] {
  if (!existsSync(filePath)) return [];

  let raw: string;
  try {
    raw = readFileSync(filePath, "utf-8");
  } catch (err) {
    console.error(`Failed to read jobs file ${filePath}:`, err);
    return [];
  }

  const jobs: JobRecord[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      jobs.push(JSON.parse(trimmed) as JobRecord);
    } catch {
      // Skip malformed lines
    }
  }
  return jobs;
}

/** Attempt to fetch live jobs from the Python gateway. Returns null on failure. */
async function fetchJobsFromGateway(): Promise<JobRecord[] | null> {
  try {
    const gatewayUrl = process.env.GATEWAY_URL || "http://localhost:18789";
    const gatewayToken = process.env.MOLTBOT_GATEWAY_TOKEN || "";

    const response = await fetch(`${gatewayUrl}/api/jobs`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        ...(gatewayToken ? { Authorization: `Bearer ${gatewayToken}` } : {}),
      },
      signal: AbortSignal.timeout(3000),
    });

    if (!response.ok) return null;

    const data = (await response.json()) as { jobs?: JobRecord[] } | JobRecord[];
    // The gateway may return { jobs: [...] } or a bare array
    if (Array.isArray(data)) return data as JobRecord[];
    if (data && Array.isArray((data as { jobs?: JobRecord[] }).jobs)) {
      return (data as { jobs: JobRecord[] }).jobs;
    }
    return null;
  } catch {
    return null; // Gateway unavailable — silent fallback
  }
}

/** Map a raw job status string to the agency ProjectStatus shape */
function jobStatusToProjectStatus(job: JobRecord): ProjectStatus {
  const rawStatus = job.status ?? "pending";

  // Normalise to the canonical ProjectStatus union
  let status: ProjectStatus["status"];
  switch (rawStatus) {
    case "done":
    case "completed":
      status = "merged";
      break;
    case "pr_ready":
      status = "planning_done";
      break;
    case "running":
    case "in_progress":
      status = "executing";
      break;
    case "failed":
      status = "failed";
      break;
    default:
      status = "planning";
  }

  return {
    status,
    plan_generated: job.created_at,
    pr_url: job.pr_url ?? null,
    tests_passed: rawStatus === "done" || rawStatus === "completed" ? true : null,
    auto_merged: rawStatus === "done" ? true : null,
    error_log: job.error ?? null,
  };
}

/** Count jobs by status category */
function countByStatus(jobs: JobRecord[]): {
  total: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
} {
  let pending = 0,
    running = 0,
    completed = 0,
    failed = 0;
  for (const job of jobs) {
    const s = job.status ?? "";
    if (s === "pending") pending++;
    else if (s === "running" || s === "in_progress") running++;
    else if (s === "done" || s === "completed" || s === "pr_ready") completed++;
    else if (s === "failed") failed++;
    else pending++; // Unknown → treat as pending
  }
  return { total: jobs.length, pending, running, completed, failed };
}

export async function handleStatusRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
  url: URL,
): Promise<boolean> {
  try {
    const cycleId = getQueryParam(url, "cycle_id");

    // Load jobs from disk first, then overlay with live gateway data
    const jobsPath = resolveJobsPath();
    let jobs = loadJobsFromFile(jobsPath);

    // Try to merge with live gateway data (gateway is source of truth for in-flight jobs)
    const liveJobs = await fetchJobsFromGateway();
    if (liveJobs && liveJobs.length > 0) {
      // Build a map of id → job so gateway data overwrites stale JSONL entries
      const merged = new Map<string, JobRecord>();
      for (const j of jobs) merged.set(j.id, j);
      for (const j of liveJobs) merged.set(j.id, j);
      jobs = Array.from(merged.values());
    }

    // ── Filter by cycle_id if provided ───────────────────────────────────────
    if (cycleId) {
      const cycleJobs = jobs.filter((j) => j.cycle_id === cycleId);

      if (cycleJobs.length === 0) {
        sendJson(res, 404, {
          error: `No jobs found for cycle_id: ${cycleId}`,
          code: "CYCLE_NOT_FOUND",
        } as ErrorResponse);
        return true;
      }

      const counts = countByStatus(cycleJobs);

      // Determine overall cycle status
      let cycleStatus: string;
      if (counts.failed > 0 && counts.running === 0 && counts.pending === 0) {
        cycleStatus = "failed";
      } else if (counts.running > 0 || counts.pending > 0) {
        cycleStatus = counts.running > 0 ? "execution_in_progress" : "planning_started";
      } else {
        cycleStatus = "completed";
      }

      // Determine current phase
      let phase: string;
      if (counts.pending === counts.total) {
        phase = "planning";
      } else if (counts.completed === counts.total) {
        phase = "review";
      } else {
        phase = "execution";
      }

      // Build per-project map
      const projects: Record<string, ProjectStatus & { deployment?: string }> = {};
      for (const job of cycleJobs) {
        const projectKey = job.project_id || job.project || job.id;
        projects[projectKey] = jobStatusToProjectStatus(job);
      }

      const completedCount = counts.completed;
      const total = counts.total;

      const response: StatusResponse = {
        cycle_id: cycleId,
        status: cycleStatus,
        phase,
        progress: {
          planning: {
            completed: cycleStatus !== "planning_started" ? total : 0,
            total,
            status: cycleStatus === "planning_started" ? "in progress" : "done",
          },
          execution: {
            completed: completedCount,
            total,
            status: counts.running > 0 ? "in progress" : counts.pending > 0 ? "queued" : "done",
          },
          review: {
            completed: cycleStatus === "completed" ? total : 0,
            total,
            status: cycleStatus === "completed" ? "done" : "queued",
          },
        },
        projects,
        updated_at: new Date().toISOString(),
        ...(cycleStatus === "completed" && {
          completed_at:
            cycleJobs
              .map((j) => j.completed_at)
              .filter(Boolean)
              .sort()
              .pop() ?? new Date().toISOString(),
        }),
      };

      sendJson(res, 200, response);
      return true;
    }

    // ── No cycle_id: return aggregate job counts ──────────────────────────────
    const counts = countByStatus(jobs);

    sendJson(res, 200, {
      total_jobs: counts.total,
      pending: counts.pending,
      running: counts.running,
      completed: counts.completed,
      failed: counts.failed,
      jobs_file: jobsPath,
      gateway_connected: liveJobs !== null,
      timestamp: new Date().toISOString(),
    });
    return true;
  } catch (err) {
    console.error("Status handler error:", err);
    sendJson(res, 500, {
      error: "Failed to retrieve cycle status",
      code: "STATUS_ERROR",
    } as ErrorResponse);
    return true;
  }
}
