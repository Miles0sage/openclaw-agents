import type { IncomingMessage, ServerResponse } from "node:http";
import type { OpenClawConfig } from "../../config/config.js";
import {
  collectAIResearch,
  loadLatestResearch,
  requireAuth,
  checkRateLimit,
  type AIScoutOptions,
} from "./ai-scout.js";

// ---------------------------------------------------------------------------
// HTTP Handler
// ---------------------------------------------------------------------------

export async function handleAIResearchRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config?: OpenClawConfig,
): Promise<void> {
  const url = new URL(req.url || "/", `http://${req.headers.host}`);
  const method = req.method?.toUpperCase();

  // CORS headers
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  // Rate limiting
  const clientIP = req.socket.remoteAddress || "unknown";
  if (!checkRateLimit(clientIP, 10)) {
    res.writeHead(429, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Rate limit exceeded" }));
    return;
  }

  try {
    if (url.pathname === "/api/research/ai/collect" && method === "POST") {
      await handleCollectRequest(req, res, config);
    } else if (url.pathname === "/api/research/ai/latest" && method === "GET") {
      await handleLatestRequest(req, res);
    } else if (url.pathname === "/api/research/ai/status" && method === "GET") {
      await handleStatusRequest(req, res);
    } else {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Endpoint not found" }));
    }
  } catch (error) {
    console.error("AI Research API error:", error);
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: "Internal server error",
        message: error instanceof Error ? error.message : "Unknown error",
      }),
    );
  }
}

async function handleCollectRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config?: OpenClawConfig,
): Promise<void> {
  // Auth check
  const auth = requireAuth();
  if (!auth.authorized) {
    res.writeHead(401, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Unauthorized" }));
    return;
  }

  // Parse request body
  let body = "";
  req.on("data", (chunk) => {
    body += chunk.toString();
  });

  await new Promise<void>((resolve) => {
    req.on("end", resolve);
  });

  let options: AIScoutOptions = { config };

  if (body) {
    try {
      const parsed = JSON.parse(body);
      options = { ...options, ...parsed };
    } catch (error) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Invalid JSON in request body" }));
      return;
    }
  }

  // Collect research
  const collection = await collectAIResearch(options);

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: collection,
      summary: {
        totalItems: collection.totalItems,
        timeframe: collection.timeframe,
        sources: collection.sources.length,
        categories: [...new Set(collection.items.map((item) => item.category))],
        topRelevance: collection.items.slice(0, 5).map((item) => ({
          title: item.title,
          score: item.relevanceScore,
          category: item.category,
        })),
      },
    }),
  );
}

async function handleLatestRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const collection = loadLatestResearch();

  if (!collection) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: "No research data found",
        message: "Run a collection first using POST /api/research/ai/collect",
      }),
    );
    return;
  }

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: collection,
    }),
  );
}

async function handleStatusRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const collection = loadLatestResearch();

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      status: {
        hasData: !!collection,
        lastCollection: collection?.collectedAt || null,
        itemCount: collection?.totalItems || 0,
        sources: collection?.sources || [],
        uptime: process.uptime(),
        timestamp: new Date().toISOString(),
      },
    }),
  );
}
