import type { IncomingMessage, ServerResponse } from "node:http";

export type SlackHttpRequestHandler = (
  req: IncomingMessage,
  res: ServerResponse,
) => Promise<void> | void;

type RegisterSlackHttpHandlerArgs = {
  path?: string | null;
  handler: SlackHttpRequestHandler;
  log?: (message: string) => void;
  accountId?: string;
};

const slackHttpRoutes = new Map<string, SlackHttpRequestHandler>();

export function normalizeSlackWebhookPath(path?: string | null): string {
  const trimmed = path?.trim();
  if (!trimmed) {
    return "/slack/events";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

export function registerSlackHttpHandler(params: RegisterSlackHttpHandlerArgs): () => void {
  const normalizedPath = normalizeSlackWebhookPath(params.path);
  if (slackHttpRoutes.has(normalizedPath)) {
    const suffix = params.accountId ? ` for account "${params.accountId}"` : "";
    params.log?.(`slack: webhook path ${normalizedPath} already registered${suffix}`);
    return () => {};
  }
  slackHttpRoutes.set(normalizedPath, params.handler);
  return () => {
    slackHttpRoutes.delete(normalizedPath);
  };
}

export async function handleSlackHttpRequest(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<boolean> {
  const url = new URL(req.url ?? "/", "http://localhost");

  // Only handle /slack/events paths
  if (!url.pathname.startsWith("/slack/events")) {
    return false;
  }

  const handler = slackHttpRoutes.get(url.pathname);
  if (!handler) {
    // Stub response for unregistered webhook (e.g., during startup)
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return true;
  }
  await handler(req, res);
  return true;
}
