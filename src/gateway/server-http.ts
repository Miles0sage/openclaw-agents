import type { TlsOptions } from "node:tls";
import type { WebSocketServer } from "ws";
import { readFileSync } from "node:fs";
import {
  createServer as createHttpServer,
  type Server as HttpServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { createServer as createHttpsServer } from "node:https";
import { resolve as pathResolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { CanvasHostHandler } from "../canvas-host/server.js";
import type { createSubsystemLogger } from "../logging/subsystem.js";
import type { GatewayWsClient } from "./server/ws-types.js";
import { resolveAgentAvatar } from "../agents/identity-avatar.js";
import { MemoryAgent } from "../agents/memory-agent.js";
import { researchAgent } from "../agents/research-agent.js";
import {
  A2UI_PATH,
  CANVAS_HOST_PATH,
  CANVAS_WS_PATH,
  handleA2uiHttpRequest,
} from "../canvas-host/a2ui.js";
import { loadConfig } from "../config/config.js";
import { performanceProfiler } from "../monitoring/performance.js";
import adminStatusRouter from "../routes/admin/status.js";
import { runAgentGraph } from "../routing/agent-graph.js";
import { handleSlackHttpRequest } from "../slack/http/index.js";
import { handleTelegramHttpRequest } from "../telegram/http/index.js";
import { createAgencyHttpHandler } from "./agency-http.js";
import { authorizeGatewayConnect, isLocalDirectRequest, type ResolvedGatewayAuth } from "./auth.js";
import {
  handleControlUiAvatarRequest,
  handleControlUiHttpRequest,
  type ControlUiRootState,
} from "./control-ui.js";
import { applyHookMappings } from "./hooks-mapping.js";
import {
  extractHookToken,
  getHookChannelError,
  type HookMessageChannel,
  type HooksConfigResolved,
  normalizeAgentPayload,
  normalizeHookHeaders,
  normalizeWakePayload,
  readJsonBody,
  resolveHookChannel,
  resolveHookDeliver,
} from "./hooks.js";
import { sendUnauthorized } from "./http-common.js";
import { getBearerToken, getHeader } from "./http-utils.js";
import { resolveGatewayClientIp } from "./net.js";
import { handleOpenAiHttpRequest } from "./openai-http.js";
import { handleOpenResponsesHttpRequest } from "./openresponses-http.js";
import { handleToolsInvokeHttpRequest } from "./tools-invoke-http.js";

type SubsystemLogger = ReturnType<typeof createSubsystemLogger>;

type HookDispatchers = {
  dispatchWakeHook: (value: { text: string; mode: "now" | "next-heartbeat" }) => void;
  dispatchAgentHook: (value: {
    message: string;
    name: string;
    wakeMode: "now" | "next-heartbeat";
    sessionKey: string;
    deliver: boolean;
    channel: HookMessageChannel;
    to?: string;
    model?: string;
    thinking?: string;
    timeoutSeconds?: number;
    allowUnsafeExternalContent?: boolean;
  }) => string;
};

function sendJson(res: ServerResponse, status: number, body: unknown) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

function isCanvasPath(pathname: string): boolean {
  return (
    pathname === A2UI_PATH ||
    pathname.startsWith(`${A2UI_PATH}/`) ||
    pathname === CANVAS_HOST_PATH ||
    pathname.startsWith(`${CANVAS_HOST_PATH}/`) ||
    pathname === CANVAS_WS_PATH
  );
}

function hasAuthorizedWsClientForIp(clients: Set<GatewayWsClient>, clientIp: string): boolean {
  for (const client of clients) {
    if (client.clientIp && client.clientIp === clientIp) {
      return true;
    }
  }
  return false;
}

async function authorizeCanvasRequest(params: {
  req: IncomingMessage;
  auth: ResolvedGatewayAuth;
  trustedProxies: string[];
  clients: Set<GatewayWsClient>;
}): Promise<boolean> {
  const { req, auth, trustedProxies, clients } = params;
  if (isLocalDirectRequest(req, trustedProxies)) {
    return true;
  }

  const token = getBearerToken(req);
  if (token) {
    const authResult = await authorizeGatewayConnect({
      auth: { ...auth, allowTailscale: false },
      connectAuth: { token, password: token },
      req,
      trustedProxies,
    });
    if (authResult.ok) {
      return true;
    }
  }

  const clientIp = resolveGatewayClientIp({
    remoteAddr: req.socket?.remoteAddress ?? "",
    forwardedFor: getHeader(req, "x-forwarded-for"),
    realIp: getHeader(req, "x-real-ip"),
    trustedProxies,
  });
  if (!clientIp) {
    return false;
  }
  return hasAuthorizedWsClientForIp(clients, clientIp);
}

export type HooksRequestHandler = (req: IncomingMessage, res: ServerResponse) => Promise<boolean>;

export function createHooksRequestHandler(
  opts: {
    getHooksConfig: () => HooksConfigResolved | null;
    bindHost: string;
    port: number;
    logHooks: SubsystemLogger;
  } & HookDispatchers,
): HooksRequestHandler {
  const { getHooksConfig, bindHost, port, logHooks, dispatchAgentHook, dispatchWakeHook } = opts;
  return async (req, res) => {
    const hooksConfig = getHooksConfig();
    if (!hooksConfig) {
      return false;
    }
    const url = new URL(req.url ?? "/", `http://${bindHost}:${port}`);
    const basePath = hooksConfig.basePath;
    if (url.pathname !== basePath && !url.pathname.startsWith(`${basePath}/`)) {
      return false;
    }

    const { token, fromQuery } = extractHookToken(req, url);
    if (!token || token !== hooksConfig.token) {
      res.statusCode = 401;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Unauthorized");
      return true;
    }
    if (fromQuery) {
      logHooks.warn(
        "Hook token provided via query parameter is deprecated for security reasons. " +
          "Tokens in URLs appear in logs, browser history, and referrer headers. " +
          "Use Authorization: Bearer <token> or X-OpenClaw-Token header instead.",
      );
    }

    if (req.method !== "POST") {
      res.statusCode = 405;
      res.setHeader("Allow", "POST");
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Method Not Allowed");
      return true;
    }

    const subPath = url.pathname.slice(basePath.length).replace(/^\/+/, "");
    if (!subPath) {
      res.statusCode = 404;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Not Found");
      return true;
    }

    const body = await readJsonBody(req, hooksConfig.maxBodyBytes);
    if (!body.ok) {
      const status = body.error === "payload too large" ? 413 : 400;
      sendJson(res, status, { ok: false, error: body.error });
      return true;
    }

    const payload = typeof body.value === "object" && body.value !== null ? body.value : {};
    const headers = normalizeHookHeaders(req);

    if (subPath === "wake") {
      const normalized = normalizeWakePayload(payload as Record<string, unknown>);
      if (!normalized.ok) {
        sendJson(res, 400, { ok: false, error: normalized.error });
        return true;
      }
      dispatchWakeHook(normalized.value);
      sendJson(res, 200, { ok: true, mode: normalized.value.mode });
      return true;
    }

    if (subPath === "agent") {
      const normalized = normalizeAgentPayload(payload as Record<string, unknown>);
      if (!normalized.ok) {
        sendJson(res, 400, { ok: false, error: normalized.error });
        return true;
      }
      const runId = dispatchAgentHook(normalized.value);
      sendJson(res, 202, { ok: true, runId });
      return true;
    }

    if (hooksConfig.mappings.length > 0) {
      try {
        const mapped = await applyHookMappings(hooksConfig.mappings, {
          payload: payload as Record<string, unknown>,
          headers,
          url,
          path: subPath,
        });
        if (mapped) {
          if (!mapped.ok) {
            sendJson(res, 400, { ok: false, error: mapped.error });
            return true;
          }
          if (mapped.action === null) {
            res.statusCode = 204;
            res.end();
            return true;
          }
          if (mapped.action.kind === "wake") {
            dispatchWakeHook({
              text: mapped.action.text,
              mode: mapped.action.mode,
            });
            sendJson(res, 200, { ok: true, mode: mapped.action.mode });
            return true;
          }
          const channel = resolveHookChannel(mapped.action.channel);
          if (!channel) {
            sendJson(res, 400, { ok: false, error: getHookChannelError() });
            return true;
          }
          const runId = dispatchAgentHook({
            message: mapped.action.message,
            name: mapped.action.name ?? "Hook",
            wakeMode: mapped.action.wakeMode,
            sessionKey: mapped.action.sessionKey ?? "",
            deliver: resolveHookDeliver(mapped.action.deliver),
            channel,
            to: mapped.action.to,
            model: mapped.action.model,
            thinking: mapped.action.thinking,
            timeoutSeconds: mapped.action.timeoutSeconds,
            allowUnsafeExternalContent: mapped.action.allowUnsafeExternalContent,
          });
          sendJson(res, 202, { ok: true, runId });
          return true;
        }
      } catch (err) {
        logHooks.warn(`hook mapping failed: ${String(err)}`);
        sendJson(res, 500, { ok: false, error: "hook mapping failed" });
        return true;
      }
    }

    res.statusCode = 404;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("Not Found");
    return true;
  };
}

// ---------------------------------------------------------------------------
// Admin status & dashboard handler
// Bridges the Express-based admin status router into the raw http handler chain.
// ---------------------------------------------------------------------------

const __dirname_server_http = dirname(fileURLToPath(import.meta.url));
// After compilation, the JS file lives in dist/ (flat bundle), so go up one level
// to reach the project root, then into public/. From the source file in
// src/gateway/ this would be ../../public/, but the bundler flattens to dist/.
const DASHBOARD_HTML_PATH = pathResolve(__dirname_server_http, "../public/dashboard.html");

/** Cached dashboard HTML (loaded once on first request). */
let dashboardHtmlCache: string | null = null;

function getDashboardHtml(): string {
  if (dashboardHtmlCache === null) {
    dashboardHtmlCache = readFileSync(DASHBOARD_HTML_PATH, "utf-8");
  }
  return dashboardHtmlCache;
}

/**
 * Handle admin status API requests and the dashboard HTML page.
 * Matches: GET /admin/status, GET /admin/logs, GET /dashboard
 * Returns true if the request was handled, false otherwise.
 */
async function handleAdminStatusRequest(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<boolean> {
  const url = new URL(req.url ?? "/", "http://localhost");
  const pathname = url.pathname;

  // Serve the dashboard HTML page
  if (req.method === "GET" && pathname === "/dashboard") {
    try {
      const html = getDashboardHtml();
      res.statusCode = 200;
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(html);
    } catch {
      res.statusCode = 500;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Dashboard not available");
    }
    return true;
  }

  // Delegate /admin/status and /admin/logs to the Express admin router
  if (pathname === "/admin/status" || pathname === "/admin/logs") {
    return new Promise<boolean>((resolve) => {
      adminStatusRouter(req as any, res as any, () => {
        // If the Express router calls next(), the route was not matched (should not happen).
        resolve(false);
      });
      // The router will end the response; consider it handled once we enter here.
      // If next() is not called, the response was handled.
      res.on("finish", () => resolve(true));
    });
  }

  return false;
}

/**
 * Initialize the performance profiler with a Redis client.
 * Call this when a Redis client becomes available during gateway startup.
 */
export function initPerformanceProfiler(redisClient: {
  lpush(key: string, ...values: string[]): Promise<number>;
  lrange(key: string, start: number, stop: number): Promise<string[]>;
  incrbyfloat(key: string, increment: number): Promise<number>;
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: { ex?: number }): Promise<string>;
  expire(key: string, seconds: number): Promise<number>;
  del(...keys: string[]): Promise<number>;
}): void {
  performanceProfiler.init(redisClient);
}

// ---------------------------------------------------------------------------
// Vision memory API handler
// ---------------------------------------------------------------------------

/** Lazily-initialised MemoryAgent singleton for vision endpoints. */
let visionMemoryAgent: MemoryAgent | null = null;

function getVisionMemoryAgent(): MemoryAgent {
  if (!visionMemoryAgent) {
    const dataDir = pathResolve(__dirname_server_http, "../data");
    visionMemoryAgent = new MemoryAgent({ dataDir });
  }
  return visionMemoryAgent;
}

/**
 * Handle vision memory API requests.
 *   GET    /api/vision/history?device_id=X&limit=20
 *   DELETE /api/vision/memories/:device_id
 * Returns true if the request was handled, false otherwise.
 */
async function handleVisionApiRequest(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  const url = new URL(req.url ?? "/", "http://localhost");
  const pathname = url.pathname;

  // GET /api/vision/history
  if (req.method === "GET" && pathname === "/api/vision/history") {
    const deviceId = url.searchParams.get("device_id");
    if (!deviceId) {
      sendJson(res, 400, { ok: false, error: "device_id query parameter is required" });
      return true;
    }
    const limit = Math.min(
      Math.max(parseInt(url.searchParams.get("limit") ?? "20", 10) || 20, 1),
      100,
    );
    const query = url.searchParams.get("q");
    try {
      const agent = getVisionMemoryAgent();
      const memories = query
        ? agent.recallVision(query, deviceId, limit)
        : agent.getRecentVision(deviceId, limit);
      sendJson(res, 200, { ok: true, count: memories.length, memories });
    } catch (err) {
      sendJson(res, 500, {
        ok: false,
        error: err instanceof Error ? err.message : "Internal error",
      });
    }
    return true;
  }

  // DELETE /api/vision/memories/:device_id
  const deleteMatch = pathname.match(/^\/api\/vision\/memories\/([^/]+)$/);
  if (req.method === "DELETE" && deleteMatch) {
    const deviceId = decodeURIComponent(deleteMatch[1]);
    try {
      const agent = getVisionMemoryAgent();
      const deleted = agent.deleteVisionMemories(deviceId);
      sendJson(res, 200, { ok: true, deleted });
    } catch (err) {
      sendJson(res, 500, {
        ok: false,
        error: err instanceof Error ? err.message : "Internal error",
      });
    }
    return true;
  }

  return false;
}

export function createGatewayHttpServer(opts: {
  canvasHost: CanvasHostHandler | null;
  clients: Set<GatewayWsClient>;
  controlUiEnabled: boolean;
  controlUiBasePath: string;
  controlUiRoot?: ControlUiRootState;
  openAiChatCompletionsEnabled: boolean;
  openResponsesEnabled: boolean;
  openResponsesConfig?: import("../config/types.gateway.js").GatewayHttpResponsesConfig;
  handleHooksRequest: HooksRequestHandler;
  handlePluginRequest?: HooksRequestHandler;
  resolvedAuth: ResolvedGatewayAuth;
  tlsOptions?: TlsOptions;
}): HttpServer {
  const {
    canvasHost,
    clients,
    controlUiEnabled,
    controlUiBasePath,
    controlUiRoot,
    openAiChatCompletionsEnabled,
    openResponsesEnabled,
    openResponsesConfig,
    handleHooksRequest,
    handlePluginRequest,
    resolvedAuth,
  } = opts;
  const httpServer: HttpServer = opts.tlsOptions
    ? createHttpsServer(opts.tlsOptions, (req, res) => {
        void handleRequest(req, res);
      })
    : createHttpServer((req, res) => {
        void handleRequest(req, res);
      });
  const handleAgencyRequest = createAgencyHttpHandler();

  async function handleRequest(req: IncomingMessage, res: ServerResponse) {
    // Don't interfere with WebSocket upgrades; ws handles the 'upgrade' event.
    if (String(req.headers.upgrade ?? "").toLowerCase() === "websocket") {
      return;
    }

    try {
      const configSnapshot = loadConfig();
      const trustedProxies = configSnapshot.gateway?.trustedProxies ?? [];
      if (await handleHooksRequest(req, res)) {
        return;
      }
      if (await handleAdminStatusRequest(req, res)) {
        return;
      }
      if (await handleVisionApiRequest(req, res)) {
        return;
      }
      if (
        await handleToolsInvokeHttpRequest(req, res, {
          auth: resolvedAuth,
          trustedProxies,
        })
      ) {
        return;
      }
      if (await handleSlackHttpRequest(req, res)) {
        return;
      }
      if (await handleTelegramHttpRequest(req, res)) {
        return;
      }
      if (await handleAgencyRequest(req, res)) {
        return;
      }
      // POST /api/route — invoke the LangGraph agent routing graph
      {
        const routeUrl = new URL(req.url ?? "/", "http://localhost");
        if (routeUrl.pathname === "/api/route" && req.method === "POST") {
          try {
            const body = await new Promise<string>((resolve, reject) => {
              let data = "";
              req.on("data", (chunk: Buffer) => {
                data += chunk.toString();
              });
              req.on("end", () => resolve(data));
              req.on("error", reject);
            });
            const parsed = JSON.parse(body || "{}") as {
              query?: string;
              sessionKey?: string;
              channel?: string;
              accountId?: string;
            };
            if (!parsed.query || typeof parsed.query !== "string") {
              sendJson(res, 400, { success: false, error: "query is required" });
              return;
            }
            const result = await runAgentGraph({
              query: parsed.query,
              sessionKey: parsed.sessionKey ?? `http:${Date.now()}`,
              channel: parsed.channel ?? "http",
              accountId: parsed.accountId ?? "default",
            });
            sendJson(res, 200, {
              success: true,
              selectedAgent: result.selectedAgent,
              finalResponse: result.finalResponse,
              cost: result.cost,
              metadata: result.metadata,
            });
          } catch (err) {
            sendJson(res, 500, {
              success: false,
              error: err instanceof Error ? err.message : "Internal error",
            });
          }
          return;
        }
      }
      // GET/POST /api/search — invoke the Research AI agent for web search
      {
        const searchUrl = new URL(req.url ?? "/", "http://localhost");
        if (
          searchUrl.pathname === "/api/search" &&
          (req.method === "GET" || req.method === "POST")
        ) {
          try {
            let query: string | undefined;
            if (req.method === "GET") {
              query = searchUrl.searchParams.get("q") ?? undefined;
            } else {
              const body = await new Promise<string>((resolve, reject) => {
                let data = "";
                req.on("data", (chunk: Buffer) => {
                  data += chunk.toString();
                });
                req.on("end", () => resolve(data));
                req.on("error", reject);
              });
              const parsed = JSON.parse(body || "{}") as { query?: string; q?: string };
              query = parsed.query ?? parsed.q;
            }
            if (!query || typeof query !== "string" || !query.trim()) {
              sendJson(res, 400, {
                success: false,
                error: 'query is required (use ?q= or {"query": "..."})',
              });
              return;
            }
            const result = await researchAgent(query.trim());
            sendJson(res, 200, {
              success: true,
              query: result.query,
              summary: result.summary,
              sources: result.sources,
              metadata: {
                fetchedUrls: result.fetchedUrls,
                totalSearchResults: result.totalSearchResults,
                tookMs: result.tookMs,
                model: result.model,
              },
            });
          } catch (err) {
            sendJson(res, 500, {
              success: false,
              error: err instanceof Error ? err.message : "Internal error",
            });
          }
          return;
        }
      }
      if (handlePluginRequest && (await handlePluginRequest(req, res))) {
        return;
      }
      if (openResponsesEnabled) {
        if (
          await handleOpenResponsesHttpRequest(req, res, {
            auth: resolvedAuth,
            config: openResponsesConfig,
            trustedProxies,
          })
        ) {
          return;
        }
      }
      if (openAiChatCompletionsEnabled) {
        if (
          await handleOpenAiHttpRequest(req, res, {
            auth: resolvedAuth,
            trustedProxies,
          })
        ) {
          return;
        }
      }
      if (canvasHost) {
        const url = new URL(req.url ?? "/", "http://localhost");
        if (isCanvasPath(url.pathname)) {
          const ok = await authorizeCanvasRequest({
            req,
            auth: resolvedAuth,
            trustedProxies,
            clients,
          });
          if (!ok) {
            sendUnauthorized(res);
            return;
          }
        }
        if (await handleA2uiHttpRequest(req, res)) {
          return;
        }
        if (await canvasHost.handleHttpRequest(req, res)) {
          return;
        }
      }
      if (controlUiEnabled) {
        if (
          handleControlUiAvatarRequest(req, res, {
            basePath: controlUiBasePath,
            resolveAvatar: (agentId) => resolveAgentAvatar(configSnapshot, agentId),
          })
        ) {
          return;
        }
        if (
          handleControlUiHttpRequest(req, res, {
            basePath: controlUiBasePath,
            config: configSnapshot,
            root: controlUiRoot,
          })
        ) {
          return;
        }
      }

      res.statusCode = 404;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Not Found");
    } catch {
      res.statusCode = 500;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Internal Server Error");
    }
  }

  return httpServer;
}

export function attachGatewayUpgradeHandler(opts: {
  httpServer: HttpServer;
  wss: WebSocketServer;
  canvasHost: CanvasHostHandler | null;
  clients: Set<GatewayWsClient>;
  resolvedAuth: ResolvedGatewayAuth;
}) {
  const { httpServer, wss, canvasHost, clients, resolvedAuth } = opts;
  httpServer.on("upgrade", (req, socket, head) => {
    void (async () => {
      if (canvasHost) {
        const url = new URL(req.url ?? "/", "http://localhost");
        if (url.pathname === CANVAS_WS_PATH) {
          const configSnapshot = loadConfig();
          const trustedProxies = configSnapshot.gateway?.trustedProxies ?? [];
          const ok = await authorizeCanvasRequest({
            req,
            auth: resolvedAuth,
            trustedProxies,
            clients,
          });
          if (!ok) {
            socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
            socket.destroy();
            return;
          }
        }
        if (canvasHost.handleUpgrade(req, socket, head)) {
          return;
        }
      }
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit("connection", ws, req);
      });
    })().catch(() => {
      socket.destroy();
    });
  });
}
