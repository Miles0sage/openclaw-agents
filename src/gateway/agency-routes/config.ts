/**
 * GET  /api/agency/config  — Return the live agency-config.json
 * PUT  /api/agency/config  — Merge updates into agency-config.json and persist
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import type { AgencyConfig, ConfigResponse, ErrorResponse } from "../agency.types.js";
import { clearAgencyConfigCache, getAgencyConfigPath } from "../agency-config-loader.js";
import { sendJson, readJsonBody } from "../agency-http.js";

/** Critical top-level keys that must never be removed by a PUT update */
const CRITICAL_KEYS = ["projects", "agency", "cycle", "costs", "model_selection"] as const;

interface ConfigUpdateRequest {
  updates: Record<string, unknown>;
}

const VALID_MODELS = new Set([
  "claude-opus-4-6",
  "claude-sonnet-4-5-20250929",
  "claude-haiku-4-5-20251001",
  "kimi-2.5",
  "kimi",
  "m2.5",
  "m2.5-lightning",
]);

const VALID_FREQUENCIES = new Set([
  "every 4h",
  "every 6h",
  "every 8h",
  "every 4 hours",
  "every 6 hours",
  "every 8 hours",
]);

/**
 * Deep-merge `source` into `target` (non-destructive: existing keys are kept
 * unless explicitly overwritten by the incoming `source`).
 */
function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const result = { ...target };
  for (const [key, value] of Object.entries(source)) {
    if (
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      typeof result[key] === "object" &&
      result[key] !== null &&
      !Array.isArray(result[key])
    ) {
      // Both sides are plain objects — recurse
      result[key] = deepMerge(
        result[key] as Record<string, unknown>,
        value as Record<string, unknown>,
      );
    } else {
      // Primitive, array, or target key is missing — overwrite
      result[key] = value;
    }
  }
  return result;
}

/** Load the config file from disk. Throws if missing or unparseable. */
function loadConfigFromDisk(configPath: string): Record<string, unknown> {
  if (!existsSync(configPath)) {
    throw new Error(`Config file not found: ${configPath}`);
  }
  const raw = readFileSync(configPath, "utf-8");
  return JSON.parse(raw) as Record<string, unknown>;
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export async function handleConfigRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
): Promise<boolean> {
  const configPath = getAgencyConfigPath();

  // ── GET: Return the live config ─────────────────────────────────────────────
  if (req.method === "GET") {
    try {
      const diskConfig = loadConfigFromDisk(configPath);
      sendJson(res, 200, {
        config: diskConfig,
        config_file: configPath,
        timestamp: new Date().toISOString(),
      });
      return true;
    } catch (err) {
      console.error("Config GET error:", err);
      sendJson(res, 500, {
        error: `Failed to read config: ${String(err)}`,
        code: "CONFIG_READ_ERROR",
      } as ErrorResponse);
      return true;
    }
  }

  // ── PUT: Merge updates and persist ─────────────────────────────────────────
  if (req.method === "PUT") {
    try {
      // Parse request body
      const bodyResult = await readJsonBody(req, 1024 * 100); // 100 KB limit
      if (!bodyResult.ok) {
        sendJson(res, 400, {
          error: "Invalid request body: " + bodyResult.error,
          code: "INVALID_BODY",
        } as ErrorResponse);
        return true;
      }

      const body = bodyResult.value as ConfigUpdateRequest;
      const updates = body.updates as Record<string, unknown> | undefined;

      if (!updates || typeof updates !== "object" || Array.isArray(updates)) {
        sendJson(res, 400, {
          error: "Missing or invalid 'updates' field — must be a plain object",
          code: "INVALID_CONFIG",
        } as ErrorResponse);
        return true;
      }

      // ── Validate cycle frequency if provided ───────────────────────────────
      const updatesCycle = asObject(updates.cycle);
      const cycleFreq =
        (updatesCycle?.frequency as string | undefined) ??
        ((updates as { cycle_frequency?: string }).cycle_frequency ?? undefined);
      if (cycleFreq !== undefined) {
        if (!VALID_FREQUENCIES.has(cycleFreq)) {
          sendJson(res, 400, {
            error: `Invalid cycle frequency: ${cycleFreq}`,
            code: "INVALID_CONFIG",
          } as ErrorResponse);
          return true;
        }
      }

      // ── Validate per_cycle_hard_cap if provided ────────────────────────────
      const updatesCosts = asObject(updates.costs);
      const perCycleCap =
        (updatesCosts?.per_cycle_hard_cap as number | undefined) ??
        ((updates as { per_cycle_hard_cap?: number }).per_cycle_hard_cap ?? undefined);
      if (perCycleCap !== undefined) {
        if (typeof perCycleCap !== "number" || perCycleCap < 1 || perCycleCap > 1000) {
          sendJson(res, 400, {
            error: "Invalid per_cycle_hard_cap. Must be between 1 and 1000",
            code: "INVALID_CONFIG",
          } as ErrorResponse);
          return true;
        }
      }

      // ── Validate monthly_hard_cap if provided ──────────────────────────────
      const monthlyHardCap =
        (updatesCosts?.monthly_hard_cap as number | undefined) ??
        ((updates as { monthly_hard_cap?: number }).monthly_hard_cap ?? undefined);
      if (monthlyHardCap !== undefined) {
        if (typeof monthlyHardCap !== "number" || monthlyHardCap < 100 || monthlyHardCap > 10000) {
          sendJson(res, 400, {
            error: "Invalid monthly_hard_cap. Must be between 100 and 10000",
            code: "INVALID_CONFIG",
          } as ErrorResponse);
          return true;
        }
      }

      // ── Validate model_selection values ───────────────────────────────────
      const modelSel = (updates as { model_selection?: Record<string, string> }).model_selection;
      if (modelSel) {
        for (const [phase, model] of Object.entries(modelSel)) {
          if (model && !VALID_MODELS.has(model)) {
            sendJson(res, 400, {
              error: `Invalid model for ${phase}: ${model}`,
              code: "INVALID_CONFIG",
            } as ErrorResponse);
            return true;
          }
        }
      }

      // ── Load existing config from disk ─────────────────────────────────────
      let existing: Record<string, unknown>;
      try {
        existing = loadConfigFromDisk(configPath);
      } catch (err) {
        sendJson(res, 500, {
          error: `Failed to read existing config: ${String(err)}`,
          code: "CONFIG_READ_ERROR",
        } as ErrorResponse);
        return true;
      }

      // ── Guard: ensure critical keys are not removed ────────────────────────
      for (const criticalKey of CRITICAL_KEYS) {
        if (criticalKey in existing && updates[criticalKey] !== undefined) {
          const incoming = updates[criticalKey];
          // If the incoming value is null or an empty object that would replace a
          // non-empty object, reject the update to protect the critical section.
          if (
            incoming === null ||
            (typeof incoming === "object" &&
              !Array.isArray(incoming) &&
              Object.keys(incoming as Record<string, unknown>).length === 0)
          ) {
            sendJson(res, 400, {
              error: `Cannot remove or empty critical key: '${criticalKey}'`,
              code: "CRITICAL_KEY_PROTECTED",
            } as ErrorResponse);
            return true;
          }
        }
      }

      // ── Merge and write back ──────────────────────────────────────────────
      const merged = deepMerge(existing, updates);

      // Safety check: make sure critical keys still exist in merged result
      for (const criticalKey of CRITICAL_KEYS) {
        if (criticalKey in existing && !(criticalKey in merged)) {
          sendJson(res, 400, {
            error: `Update would delete critical key '${criticalKey}'. Rejected.`,
            code: "CRITICAL_KEY_DELETED",
          } as ErrorResponse);
          return true;
        }
      }

      try {
        writeFileSync(configPath, JSON.stringify(merged, null, 2), "utf-8");
      } catch (writeErr) {
        sendJson(res, 500, {
          error: `Failed to write config: ${String(writeErr)}`,
          code: "CONFIG_WRITE_ERROR",
        } as ErrorResponse);
        return true;
      }

      // Bust in-process config cache so the next request picks up fresh values
      clearAgencyConfigCache();

      // ── Send Slack notification if webhook is available ───────────────────
      let slackSent = false;
      const slackWebhookUrl = process.env.SLACK_WEBHOOK_URL || config.agency?.slack_webhook;
      if (slackWebhookUrl) {
        try {
          await fetch(slackWebhookUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text: `*Agency config updated*\nFile: \`${configPath}\`\nKeys changed: ${Object.keys(updates).join(", ")}`,
            }),
            signal: AbortSignal.timeout(5000),
          });
          slackSent = true;
        } catch (slackErr) {
          console.warn("Slack notification failed after config update:", slackErr);
        }
      }

      // ── Track what changed (old → new) ───────────────────────────────────
      const changesApplied: Record<string, unknown> = {};
      for (const [key, newValue] of Object.entries(updates)) {
        changesApplied[key] = {
          old: existing[key] ?? null,
          new: newValue,
        };
      }

      const response: ConfigResponse = {
        status: "updated",
        timestamp: new Date().toISOString(),
        changes_applied: changesApplied,
        config_file_updated: configPath,
        next_cycle: new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString(),
        slack_notification_sent: slackSent,
        note: "Changes take effect on next cycle",
      };

      sendJson(res, 200, response);
      return true;
    } catch (err) {
      console.error("Config PUT error:", err);
      sendJson(res, 500, {
        error: "Failed to update configuration",
        code: "CONFIG_ERROR",
      } as ErrorResponse);
      return true;
    }
  }

  // ── Unsupported method ──────────────────────────────────────────────────────
  sendJson(res, 405, {
    error: "Method Not Allowed. Use GET or PUT.",
    code: "METHOD_NOT_ALLOWED",
  } as ErrorResponse);
  return true;
}
