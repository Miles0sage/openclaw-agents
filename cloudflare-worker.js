/**
 * OpenClaw Cloudflare Worker
 * Proxies requests to OpenClaw Gateway
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // CORS headers
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    };

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // Validate token
    const token =
      url.searchParams.get("token") || request.headers.get("Authorization")?.replace("Bearer ", "");

    const EXPECTED_TOKEN =
      env.OPENCLAW_TOKEN || "7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d";

    if (token !== EXPECTED_TOKEN) {
      return new Response(
        JSON.stringify({
          error: "Unauthorized",
          message: "Invalid or missing token",
        }),
        {
          status: 401,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }

    // Get OpenClaw gateway URL from environment
    const GATEWAY_URL = env.OPENCLAW_GATEWAY || "http://<your-vps-ip>:18789";

    // Health check
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(
        JSON.stringify({
          status: "online",
          worker: "oversserclaw-worker",
          gateway: GATEWAY_URL,
          timestamp: new Date().toISOString(),
        }),
        {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }

    // Proxy to OpenClaw Gateway
    try {
      const openclawUrl = `${GATEWAY_URL}${url.pathname}${url.search}`;

      console.log(`Proxying ${request.method} ${openclawUrl}`);

      const response = await fetch(openclawUrl, {
        method: request.method,
        headers: {
          "Content-Type": request.headers.get("Content-Type") || "application/json",
        },
        body:
          request.method !== "GET" && request.method !== "HEAD" ? await request.text() : undefined,
      });

      // Get response body
      const responseBody = await response.text();

      // Return proxied response
      return new Response(responseBody, {
        status: response.status,
        headers: {
          ...corsHeaders,
          "Content-Type": response.headers.get("Content-Type") || "application/json",
        },
      });
    } catch (error) {
      console.error("Proxy error:", error);

      return new Response(
        JSON.stringify({
          error: "Gateway Error",
          message: error.message,
          gateway: GATEWAY_URL,
        }),
        {
          status: 502,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }
  },
};
