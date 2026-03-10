/**
 * POST /api/agency/trigger
 * Start a new agency cycle (planning + execution + review for all or specified projects)
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import { existsSync, mkdirSync, appendFileSync } from "node:fs";
import type { AgencyConfig, TriggerResponse, ErrorResponse } from "../agency.types.js";
import { validateProjects, getEnabledProjects } from "../agency-config-loader.js";
import { sendJson, readJsonBody, getQueryParam } from "../agency-http.js";

interface TriggerRequest {
  projects?: string[]; // Optional: specific projects to run
  force?: boolean; // Optional: skip change detection
  task?: string; // Optional: task description for the job
  priority?: string; // Optional: P0/P1/P2
}

// Default persistent path for jobs, fallback to /tmp
const JOBS_DIR =
  process.env.JOBS_DIR ||
  (existsSync("./data/jobs") ? "./data/jobs" : "/tmp/openclaw_jobs");

export async function handleTriggerRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
): Promise<boolean> {
  try {
    // Parse request body
    const bodyResult = await readJsonBody(req, 1024 * 100); // 100KB limit
    if (!bodyResult.ok) {
      sendJson(res, 400, {
        error: "Invalid request body: " + bodyResult.error,
        code: "INVALID_BODY",
      } as ErrorResponse);
      return true;
    }

    const body = bodyResult.value as TriggerRequest;
    const requestedProjects = body.projects || [];
    const force = body.force ?? false;
    const taskDesc = body.task || "Agency cycle triggered via API";
    const priority = body.priority || "P1";

    // Determine which projects to run
    const projectsToRun =
      requestedProjects.length > 0 ? requestedProjects : config.projects.map((p) => p.id);

    // Validate requested projects exist
    if (requestedProjects.length > 0) {
      const validation = validateProjects(config, requestedProjects);
      if (!validation.valid) {
        sendJson(res, 400, {
          error: `Invalid projects: ${validation.invalidProjects.join(", ")}`,
          code: "INVALID_PROJECT",
          valid_projects: config.projects.map((p) => p.id),
        } as ErrorResponse);
        return true;
      }
    }

    // Generate cycle ID: YYYY-MM-DD-NNN
    const cycleId = generateCycleId();

    // Ensure jobs directory exists
    try {
      mkdirSync(JOBS_DIR, { recursive: true });
    } catch (_) {
      // Directory may already exist — ignore
    }

    const jobsFile = `${JOBS_DIR}/jobs.jsonl`;
    const createdJobs: string[] = [];
    const now = new Date().toISOString();

    // Write one job per project to the Python gateway and to the local JSONL file
    for (const projectId of projectsToRun) {
      const jobId = `job-${generateJobSuffix()}`;

      const jobRecord = {
        id: jobId,
        project: projectId,
        cycle_id: cycleId,
        task: taskDesc,
        priority,
        status: "pending",
        force_skip_change_detection: force,
        created_at: now,
        pr_url: null,
        branch_name: null,
        approved_by: null,
        completed_at: null,
      };

      // 1. Try to POST to the Python gateway's /api/jobs endpoint
      let gatewayJobId: string | null = null;
      try {
        const gatewayUrl = process.env.GATEWAY_URL || "http://localhost:18789";
        const gatewayToken = process.env.MOLTBOT_GATEWAY_TOKEN || "";
        const gatewayResponse = await fetch(`${gatewayUrl}/api/jobs`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(gatewayToken ? { Authorization: `Bearer ${gatewayToken}` } : {}),
          },
          body: JSON.stringify({
            project: projectId,
            task: taskDesc,
            priority,
            cycle_id: cycleId,
          }),
          signal: AbortSignal.timeout(5000),
        });

        if (gatewayResponse.ok) {
          const gatewayData = (await gatewayResponse.json()) as { id?: string; job_id?: string };
          gatewayJobId = gatewayData.id || gatewayData.job_id || null;
        }
      } catch (fetchErr) {
        // Gateway unavailable — continue with local-only write
        console.warn(`Gateway POST failed for project ${projectId}:`, fetchErr);
      }

      // Use gateway job ID if we got one; otherwise keep the locally generated ID
      const finalJobId = gatewayJobId || jobId;

      // 2. Append to local JSONL file
      try {
        appendFileSync(jobsFile, JSON.stringify({ ...jobRecord, id: finalJobId }) + "\n", "utf-8");
      } catch (writeErr) {
        console.error("Failed to write job to local JSONL:", writeErr);
      }

      createdJobs.push(finalJobId);
    }

    // Send Slack notification if webhook URL is configured
    const slackWebhookUrl = process.env.SLACK_WEBHOOK_URL || config.agency?.slack_webhook;
    if (slackWebhookUrl) {
      try {
        await fetch(slackWebhookUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: `Agency cycle *${cycleId}* started`,
            blocks: [
              {
                type: "section",
                text: {
                  type: "mrkdwn",
                  text: [
                    `*Agency Cycle Triggered*`,
                    `Cycle ID: \`${cycleId}\``,
                    `Projects queued: ${projectsToRun.length} (${projectsToRun.join(", ")})`,
                    `Task: ${taskDesc}`,
                    `Force: ${force}`,
                    `Jobs created: ${createdJobs.join(", ")}`,
                  ].join("\n"),
                },
              },
            ],
          }),
          signal: AbortSignal.timeout(5000),
        });
      } catch (slackErr) {
        // Non-fatal — log and continue
        console.warn("Slack notification failed:", slackErr);
      }
    }

    // Return response
    const response: TriggerResponse = {
      cycle_id: cycleId,
      status: "planning_started",
      projects_queued: projectsToRun.length,
      estimated_cost: `$${(projectsToRun.length * 3.8).toFixed(2)}`,
      estimated_time_minutes: 45,
      timestamp: now,
      job_urls: {
        planning_queue: jobsFile,
        tracking_url: `/api/agency/status?cycle_id=${cycleId}`,
      },
    };

    sendJson(res, 200, response);
    return true;
  } catch (err) {
    console.error("Trigger handler error:", err);
    sendJson(res, 500, {
      error: "Failed to start cycle",
      code: "TRIGGER_ERROR",
    } as ErrorResponse);
    return true;
  }
}

/**
 * Generate a cycle ID in format: YYYY-MM-DD-NNN
 */
function generateCycleId(): string {
  const now = new Date();
  const dateStr = now.toISOString().split("T")[0]; // YYYY-MM-DD
  const randomNum = String(Math.floor(Math.random() * 1000)).padStart(3, "0"); // NNN
  return `${dateStr}-${randomNum}`;
}

/**
 * Generate a job ID suffix: YYYYMMDD-HHMMSS-<hex>
 */
function generateJobSuffix(): string {
  const now = new Date();
  const datePart = now
    .toISOString()
    .replace(/[-:T.Z]/g, "")
    .slice(0, 14); // YYYYMMDDHHmmss
  const hex = Math.floor(Math.random() * 0xffffffff)
    .toString(16)
    .padStart(8, "0");
  return `${datePart}-${hex}`;
}
