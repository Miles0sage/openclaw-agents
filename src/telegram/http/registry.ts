import type { IncomingMessage, ServerResponse } from "node:http";
import { createHmac } from "node:crypto";
import { logVerbose } from "../../globals.js";

export type TelegramHttpRequestHandler = (
  req: IncomingMessage,
  res: ServerResponse,
) => Promise<void> | void;

type RegisterTelegramHttpHandlerArgs = {
  path?: string | null;
  token: string;
  secret?: string;
  handler: TelegramHttpRequestHandler;
  log?: (message: string) => void;
  accountId?: string;
};

const telegramHttpRoutes = new Map<
  string,
  {
    handler: TelegramHttpRequestHandler;
    token: string;
    secret?: string;
  }
>();

export function normalizeTelegramWebhookPath(path?: string | null): string {
  const trimmed = path?.trim();
  if (!trimmed) {
    return "/telegram/webhook";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

/**
 * Verify Telegram secret token (if configured)
 * Telegram sends X-Telegram-Bot-Api-Secret-Token header
 */
function verifyTelegramSecret(req: IncomingMessage, expectedSecret: string | undefined): boolean {
  if (!expectedSecret) {
    // No secret configured, skip verification
    return true;
  }

  const headerToken = req.headers["x-telegram-bot-api-secret-token"];
  if (!headerToken) {
    logVerbose("telegram: missing X-Telegram-Bot-Api-Secret-Token header");
    return false;
  }

  const token = Array.isArray(headerToken) ? headerToken[0] : headerToken;
  return token === expectedSecret;
}

export function registerTelegramHttpHandler(params: RegisterTelegramHttpHandlerArgs): () => void {
  const normalizedPath = normalizeTelegramWebhookPath(params.path);
  if (telegramHttpRoutes.has(normalizedPath)) {
    const suffix = params.accountId ? ` for account "${params.accountId}"` : "";
    params.log?.(`telegram: webhook path ${normalizedPath} already registered${suffix}`);
    return () => {};
  }
  telegramHttpRoutes.set(normalizedPath, {
    handler: params.handler,
    token: params.token,
    secret: params.secret,
  });
  return () => {
    telegramHttpRoutes.delete(normalizedPath);
  };
}

export async function handleTelegramHttpRequest(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<boolean> {
  const url = new URL(req.url ?? "/", "http://localhost");

  // Only handle /telegram/webhook paths
  if (!url.pathname.startsWith("/telegram/webhook")) {
    return false;
  }

  const route = telegramHttpRoutes.get(url.pathname);
  if (!route) {
    // Stub response for unregistered webhook (e.g., during startup)
    logVerbose(`telegram: webhook received on ${url.pathname} but no handler registered`);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return true;
  }

  // Verify Telegram secret if configured
  if (!verifyTelegramSecret(req, route.secret)) {
    res.writeHead(403, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Invalid secret token" }));
    return true;
  }

  await route.handler(req, res);
  return true;
}

/** For testing only: clears all registered routes */
export function clearTelegramHttpRoutes(): void {
  telegramHttpRoutes.clear();
}
