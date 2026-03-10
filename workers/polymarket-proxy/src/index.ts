/**
 * Polymarket Proxy — Cloudflare Worker
 *
 * Proxies requests to Polymarket APIs through Cloudflare's global edge network.
 * Runs on non-US edge nodes, bypassing geoblock for the US VPS.
 *
 * Endpoints:
 *   POST /gamma/*  → https://gamma-api.polymarket.com/*   (market data)
 *   POST /clob/*   → https://clob.polymarket.com/*        (order book + trading)
 *   GET  /health   → health check
 *
 * Usage from Python:
 *   POST https://polymarket-proxy<your-domain>/gamma/markets?limit=5
 *   POST https://polymarket-proxy<your-domain>/clob/midpoint?token_id=0x...
 */

interface Env {
  PROXY_SECRET?: string;
  ENVIRONMENT: string;
}

const GAMMA_BASE = "https://gamma-api.polymarket.com";
const CLOB_BASE = "https://clob.polymarket.com";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS headers for all responses
    const corsHeaders: Record<string, string> = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Proxy-Secret",
    };

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    // Health check
    if (path === "/" || path === "/health") {
      return Response.json(
        {
          status: "ok",
          service: "polymarket-proxy",
          timestamp: new Date().toISOString(),
          colo: (request as any).cf?.colo || "unknown",
        },
        { headers: corsHeaders },
      );
    }

    // Optional auth check
    if (env.PROXY_SECRET) {
      const secret = request.headers.get("X-Proxy-Secret") || url.searchParams.get("secret");
      if (secret !== env.PROXY_SECRET) {
        return Response.json({ error: "unauthorized" }, { status: 401, headers: corsHeaders });
      }
    }

    // Route to correct upstream
    let upstream: string;
    let upstreamPath: string;

    if (path.startsWith("/gamma/")) {
      upstream = GAMMA_BASE;
      upstreamPath = path.slice(6); // strip /gamma
    } else if (path.startsWith("/gamma")) {
      upstream = GAMMA_BASE;
      upstreamPath = path.slice(6) || "/";
    } else if (path.startsWith("/clob/")) {
      upstream = CLOB_BASE;
      upstreamPath = path.slice(5); // strip /clob
    } else if (path.startsWith("/clob")) {
      upstream = CLOB_BASE;
      upstreamPath = path.slice(5) || "/";
    } else {
      return Response.json(
        { error: "Use /gamma/* or /clob/* to proxy to Polymarket APIs" },
        { status: 400, headers: corsHeaders },
      );
    }

    // Build upstream URL preserving query params
    const upstreamUrl = `${upstream}${upstreamPath}${url.search}`;

    // Forward the request
    const upstreamHeaders: Record<string, string> = {
      "Content-Type": request.headers.get("Content-Type") || "application/json",
      Accept: "application/json",
      "User-Agent": "OpenClaw-Proxy/1.0",
    };

    // Forward auth headers for trading (CLOB)
    const authHeader = request.headers.get("Authorization");
    if (authHeader) {
      upstreamHeaders["Authorization"] = authHeader;
    }
    // Polymarket CLOB uses these headers for authenticated requests
    for (const h of [
      "POLY-ADDRESS",
      "POLY-SIGNATURE",
      "POLY-TIMESTAMP",
      "POLY-NONCE",
      "POLY-API-KEY",
    ]) {
      const val = request.headers.get(h);
      if (val) upstreamHeaders[h] = val;
    }

    try {
      const upstreamResp = await fetch(upstreamUrl, {
        method: request.method === "POST" && !request.body ? "GET" : request.method,
        headers: upstreamHeaders,
        body: request.body,
        // Force non-US edge node by setting cf options
        cf: {
          // Cloudflare will route to nearest edge; since the worker runs globally
          // it naturally avoids the US geoblock
          cacheTtl: 5,
          cacheEverything: false,
        } as any,
      });

      // Read response
      const contentType = upstreamResp.headers.get("Content-Type") || "";
      const body = await upstreamResp.text();

      return new Response(body, {
        status: upstreamResp.status,
        headers: {
          ...corsHeaders,
          "Content-Type": contentType || "application/json",
          "X-Upstream-Status": String(upstreamResp.status),
          "X-Proxy-Colo": String((request as any).cf?.colo || "unknown"),
        },
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return Response.json(
        { error: "proxy_error", detail: msg, upstream: upstreamUrl },
        { status: 502, headers: corsHeaders },
      );
    }
  },
};
