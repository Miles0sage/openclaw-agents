/**
 * Agency HTTP Handler
 * Main request handler for the 24/7 agentic agency system
 * Implements handler chain pattern used throughout OpenClaw
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import type { ErrorResponse } from "./agency.types.js";
import { validateAgencyToken, loadAgencyConfig } from "./agency-config-loader.js";
import { handleConfigRequest } from "./agency-routes/config.js";
import { handleCostsRequest } from "./agency-routes/costs.js";
import { handleStatusRequest } from "./agency-routes/status.js";
import { handleTriggerRequest } from "./agency-routes/trigger.js";

/**
 * Request handler type (returns true if handled, false to pass to next handler)
 */
export type AgencyRequestHandler = (req: IncomingMessage, res: ServerResponse) => Promise<boolean>;

/**
 * Create the agency HTTP request handler
 * Integrates with OpenClaw's handler chain pattern
 */
export function createAgencyHttpHandler(): AgencyRequestHandler {
  return async (req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const pathname = url.pathname;

    // Only handle /api/agency/* paths
    if (!pathname.startsWith("/api/agency/")) {
      return false;
    }

    try {
      // Check authentication first
      const token = req.headers.authorization?.replace("Bearer ", "");
      if (!validateAgencyToken(token)) {
        sendJson(res, 401, {
          error: "Invalid or missing authorization token",
          code: "AUTH_FAILED",
        } as ErrorResponse);
        return true;
      }

      // Load config once
      let config;
      try {
        config = loadAgencyConfig();
      } catch (err) {
        sendJson(res, 500, {
          error: "Failed to load agency configuration",
          code: "CONFIG_LOAD_ERROR",
        } as ErrorResponse);
        return true;
      }

      // Route to appropriate handler based on method + path
      if (pathname === "/api/agency/trigger" && req.method === "POST") {
        return await handleTriggerRequest(req, res, config);
      }

      if (pathname === "/api/agency/status" && req.method === "GET") {
        return await handleStatusRequest(req, res, config, url);
      }

      if (pathname === "/api/agency/costs" && req.method === "GET") {
        return await handleCostsRequest(req, res, config, url);
      }

      if (pathname === "/api/agency/config") {
        return await handleConfigRequest(req, res, config);
      }

      // 404 for unmatched /api/agency/* paths
      sendJson(res, 404, {
        error: "Not Found",
        code: "NOT_FOUND",
      } as ErrorResponse);
      return true;
    } catch (err) {
      console.error("Agency handler error:", err);
      sendJson(res, 500, {
        error: "Internal Server Error",
        code: "INTERNAL_ERROR",
      } as ErrorResponse);
      return true;
    }
  };
}

/**
 * Send JSON response helper (used by all handlers)
 */
export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

/**
 * Read JSON request body with size limit
 */
export async function readJsonBody(
  req: IncomingMessage,
  maxBytes: number = 1024 * 1024, // 1MB default
): Promise<{ ok: true; value: unknown } | { ok: false; error: string }> {
  return new Promise((resolve) => {
    let data = "";
    let isAborted = false;

    req.on("data", (chunk) => {
      data += chunk.toString();
      if (data.length > maxBytes) {
        isAborted = true;
        req.pause();
        resolve({ ok: false, error: "payload too large" });
      }
    });

    req.on("end", () => {
      if (isAborted) return;
      try {
        const parsed = data ? JSON.parse(data) : {};
        resolve({ ok: true, value: parsed });
      } catch (err) {
        resolve({ ok: false, error: "invalid json" });
      }
    });

    req.on("error", (err) => {
      resolve({ ok: false, error: String(err) });
    });
  });
}

/**
 * Get Bearer token from Authorization header
 */
export function getBearerToken(req: IncomingMessage): string | undefined {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith("Bearer ")) {
    return undefined;
  }
  return auth.slice(7);
}

/**
 * Parse query parameter
 */
export function getQueryParam(url: URL, name: string): string | null {
  return url.searchParams.get(name);
}

/**
 * Parse multiple query parameters
 */
export function getQueryParams(url: URL, names: string[]): Record<string, string | null> {
  const result: Record<string, string | null> = {};
  for (const name of names) {
    result[name] = url.searchParams.get(name);
  }
  return result;
}
