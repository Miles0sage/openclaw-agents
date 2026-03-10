import type { IncomingMessage, ServerResponse } from "node:http";
import {
  loadClassifiedResearch,
  filterClassifiedItems,
  getTopPriorityItems,
  getItemsByBucket,
  getItemById,
  getBucketSummary,
  requireAuth,
  checkRateLimit,
  type ClassificationFilters,
} from "./ai-classified.js";

// ---------------------------------------------------------------------------
// HTTP Handler
// ---------------------------------------------------------------------------

export async function handleClassifiedResearchRequest(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const url = new URL(req.url || "/", `http://${req.headers.host}`);
  const method = req.method?.toUpperCase();

  // CORS headers
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  // Rate limiting
  const clientIP = req.socket.remoteAddress || "unknown";
  if (!checkRateLimit(clientIP, 20)) {
    res.writeHead(429, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Rate limit exceeded" }));
    return;
  }

  try {
    if (url.pathname === "/api/research/classified" && method === "GET") {
      await handleClassifiedDataRequest(req, res, url);
    } else if (url.pathname === "/api/research/classified/priority" && method === "GET") {
      await handlePriorityRequest(req, res, url);
    } else if (url.pathname === "/api/research/classified/buckets" && method === "GET") {
      await handleBucketsRequest(req, res, url);
    } else if (url.pathname.startsWith("/api/research/classified/bucket/") && method === "GET") {
      await handleBucketRequest(req, res, url);
    } else if (url.pathname.startsWith("/api/research/classified/item/") && method === "GET") {
      await handleItemRequest(req, res, url);
    } else if (url.pathname === "/api/research/classified/summary" && method === "GET") {
      await handleSummaryRequest(req, res);
    } else {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Endpoint not found" }));
    }
  } catch (error) {
    console.error("Classified Research API error:", error);
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: "Internal server error",
        message: error instanceof Error ? error.message : "Unknown error",
      }),
    );
  }
}

async function handleClassifiedDataRequest(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<void> {
  const data = loadClassifiedResearch();

  if (!data) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: "No classified research data found",
        message: "Classification data not available",
      }),
    );
    return;
  }

  // Parse query parameters for filtering
  const filters: ClassificationFilters = {};

  if (url.searchParams.has("bucket")) {
    filters.bucket = url.searchParams.get("bucket")!;
  }

  if (url.searchParams.has("min_impact")) {
    filters.min_impact_score = parseInt(url.searchParams.get("min_impact")!);
  }

  if (url.searchParams.has("min_urgency")) {
    filters.min_urgency_score = parseInt(url.searchParams.get("min_urgency")!);
  }

  if (url.searchParams.has("min_combined")) {
    filters.min_combined_score = parseInt(url.searchParams.get("min_combined")!);
  }

  if (url.searchParams.has("tags")) {
    filters.tags = url.searchParams
      .get("tags")!
      .split(",")
      .map((tag) => tag.trim());
  }

  if (url.searchParams.has("priority")) {
    const priority = url.searchParams.get("priority")!;
    if (
      [
        "critical_urgent",
        "high_impact_urgent",
        "high_impact_medium_urgency",
        "medium_priority",
      ].includes(priority)
    ) {
      filters.priority_level = priority as any;
    }
  }

  const filteredData =
    Object.keys(filters).length > 0 ? filterClassifiedItems(data, filters) : data;

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: filteredData,
      filters_applied: filters,
      total_items: Object.values(filteredData.classified_findings).reduce(
        (sum, items) => sum + items.length,
        0,
      ),
    }),
  );
}

async function handlePriorityRequest(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<void> {
  const data = loadClassifiedResearch();

  if (!data) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "No classified research data found" }));
    return;
  }

  const limit = parseInt(url.searchParams.get("limit") || "10");
  const topPriority = getTopPriorityItems(data, limit);

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: {
        top_priority_items: topPriority,
        priority_matrix: data.priority_matrix,
        limit_applied: limit,
      },
    }),
  );
}

async function handleBucketsRequest(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<void> {
  const data = loadClassifiedResearch();

  if (!data) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "No classified research data found" }));
    return;
  }

  const bucketSummary = getBucketSummary(data);
  const availableBuckets = Object.keys(data.classified_findings);

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: {
        available_buckets: availableBuckets,
        bucket_summary: bucketSummary,
        total_buckets: availableBuckets.length,
      },
    }),
  );
}

async function handleBucketRequest(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<void> {
  const data = loadClassifiedResearch();

  if (!data) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "No classified research data found" }));
    return;
  }

  const bucketName = url.pathname.split("/").pop();
  if (!bucketName) {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Bucket name required" }));
    return;
  }

  const items = getItemsByBucket(data, bucketName);

  if (items.length === 0) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: "Bucket not found or empty",
        available_buckets: Object.keys(data.classified_findings),
      }),
    );
    return;
  }

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: {
        bucket: bucketName,
        items: items,
        count: items.length,
      },
    }),
  );
}

async function handleItemRequest(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<void> {
  const data = loadClassifiedResearch();

  if (!data) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "No classified research data found" }));
    return;
  }

  const itemId = url.pathname.split("/").pop();
  if (!itemId) {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Item ID required" }));
    return;
  }

  const item = getItemById(data, itemId);

  if (!item) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Item not found" }));
    return;
  }

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: item,
    }),
  );
}

async function handleSummaryRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const data = loadClassifiedResearch();

  if (!data) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "No classified research data found" }));
    return;
  }

  const bucketSummary = getBucketSummary(data);
  const topPriority = getTopPriorityItems(data, 5);

  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      success: true,
      data: {
        classification_metadata: data.metadata,
        summary_statistics: data.summary_statistics,
        bucket_summary: bucketSummary,
        top_priority_items: topPriority,
        deduplication_notes: data.deduplication_notes,
        generated_at: new Date().toISOString(),
      },
    }),
  );
}
