import type { RuntimeEnv } from "../runtime.js";
import type { TelegramMessageContext } from "./bot-message-context.js";
import { logVerbose } from "../globals.js";

export type HttpGatewayConfig = {
  enabled: boolean;
  url: string;
  token?: string;
};

/**
 * Send Telegram message to HTTP gateway with session memory support
 * This allows external gateways to maintain conversation history per user/chat
 */
export async function dispatchToHttpGateway(params: {
  context: TelegramMessageContext;
  runtime: RuntimeEnv;
  gatewayConfig: HttpGatewayConfig;
}): Promise<{
  ok: boolean;
  response?: string;
  error?: string;
  sessionKey?: string;
}> {
  const { context, runtime, gatewayConfig } = params;

  if (!gatewayConfig.enabled || !gatewayConfig.url) {
    return { ok: false, error: "HTTP gateway not configured" };
  }

  try {
    const { ctxPayload, route, chatId, msg, isGroup } = context;

    // Build session key for memory persistence
    // Format: telegram:{userId}:{chatId} for DMs, telegram:group:{groupId} for groups
    const sessionKey = route.sessionKey || `telegram:${msg.from?.id || chatId}:${chatId}`;

    logVerbose(
      `telegram: dispatching to HTTP gateway ${gatewayConfig.url} with sessionKey=${sessionKey}`,
    );

    // Prepare payload for HTTP gateway
    const payload = {
      channel: "telegram",
      sessionKey,
      chatId: String(chatId),
      userId: msg.from?.id,
      username: msg.from?.username,
      isGroup,
      message: ctxPayload.Body || ctxPayload.BodyForAgent || "",
      messageId: msg.message_id,
      timestamp: (msg.date || 0) * 1000,
      agentId: route.agentId || "main",
      metadata: {
        threadId: context.threadSpec.id as string | undefined,
        accountId: route.accountId,
      },
    };

    // Make HTTP request to gateway
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (gatewayConfig.token) {
      headers["X-Auth-Token"] = gatewayConfig.token;
    }

    const response = await fetch(`${gatewayConfig.url}/api/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        content: payload.message,
        sessionKey,
        agent_id: payload.agentId,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      return {
        ok: false,
        error: `HTTP ${response.status}: ${errorText}`,
        sessionKey,
      };
    }

    const data = (await response.json()) as {
      response?: string;
      error?: string;
    };

    logVerbose(`telegram: HTTP gateway responded successfully for ${sessionKey}`);

    return {
      ok: true,
      response: data.response || data.error,
      sessionKey,
    };
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    logVerbose(`telegram: HTTP gateway error: ${errorMessage}`);
    return {
      ok: false,
      error: errorMessage,
    };
  }
}

/**
 * Check if HTTP gateway is enabled for Telegram account
 */
export function isHttpGatewayEnabled(config: unknown): config is HttpGatewayConfig {
  if (!config || typeof config !== "object") return false;
  const cfg = config as Record<string, unknown>;
  return Boolean(cfg.enabled && typeof cfg.url === "string");
}
