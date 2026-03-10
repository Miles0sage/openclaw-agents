/**
 * Cline Integration Plugin for OpenClaw
 * Allows Cline (VS Code extension) to interact with OpenClaw agents
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { Type } from "@sinclair/typebox";

interface ClineMessage {
  id: string;
  timestamp: number;
  agent: string;
  message: string;
  code?: string;
  action?: "edit" | "review" | "implement" | "debug";
}

export default function (api: OpenClawPluginApi) {
  // Queue for messages between OpenClaw and Cline
  const clineQueue: ClineMessage[] = [];
  const maxQueueSize = 100;

  // Clean old messages
  setInterval(
    () => {
      const oneHourAgo = Date.now() - 60 * 60 * 1000;
      const filtered = clineQueue.filter((m) => m.timestamp > oneHourAgo);
      clineQueue.length = 0;
      clineQueue.push(...filtered);
    },
    5 * 60 * 1000,
  ); // Every 5 minutes

  // Tool: Send message to Cline
  api.registerTool({
    name: "cline_send",
    description:
      "Send a message, code snippet, or task to Cline running in VS Code. Use this when you want Cline to implement, review, or edit code.",
    parameters: Type.Object({
      message: Type.String({
        description: "Message or instruction for Cline",
      }),
      code: Type.Optional(
        Type.String({
          description: "Code snippet to send (optional)",
        }),
      ),
      action: Type.Optional(
        Type.Union(
          [
            Type.Literal("edit"),
            Type.Literal("review"),
            Type.Literal("implement"),
            Type.Literal("debug"),
          ],
          {
            description: "What action should Cline take?",
          },
        ),
      ),
      filepath: Type.Optional(
        Type.String({
          description: "File path for the code (if applicable)",
        }),
      ),
    }),
    async execute(_id, params) {
      const messageId = `cline_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

      const message: ClineMessage = {
        id: messageId,
        timestamp: Date.now(),
        agent: "OpenClaw Agent",
        message: params.message,
        code: params.code,
        action: params.action,
      };

      clineQueue.push(message);

      // Keep queue size manageable
      if (clineQueue.length > maxQueueSize) {
        clineQueue.shift();
      }

      return {
        content: [
          {
            type: "text",
            text:
              `✅ Message queued for Cline (ID: ${messageId})\n\n` +
              `Queue size: ${clineQueue.length}\n` +
              `Action: ${params.action || "none"}\n` +
              `Cline will receive this when it polls the endpoint.`,
          },
        ],
      };
    },
  });

  // Tool: Receive messages from Cline (for OpenClaw agents)
  api.registerTool({
    name: "cline_receive",
    description:
      "Check for new messages from Cline. Use this to see if Cline has completed tasks or sent updates.",
    parameters: Type.Object({
      since: Type.Optional(
        Type.Number({
          description: "Unix timestamp - only get messages after this time",
        }),
      ),
    }),
    async execute(_id, params) {
      const since = params.since || 0;
      const messages = clineQueue.filter((m) => m.timestamp > since && m.agent === "Cline");

      if (messages.length === 0) {
        return {
          content: [
            {
              type: "text",
              text: "No new messages from Cline.",
            },
          ],
        };
      }

      const formattedMessages = messages
        .map(
          (m) =>
            `**[${new Date(m.timestamp).toISOString()}]** ${m.message}` +
            (m.code ? `\n\`\`\`\n${m.code}\n\`\`\`` : ""),
        )
        .join("\n\n");

      return {
        content: [
          {
            type: "text",
            text: `📨 ${messages.length} new message(s) from Cline:\n\n${formattedMessages}`,
          },
        ],
      };
    },
  });

  // HTTP Endpoints for Cline to interact with
  api.registerHttpHandler(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host}`);

    // POST /api/cline/send - Cline sends messages to OpenClaw
    if (req.method === "POST" && url.pathname === "/api/cline/send") {
      const body = await readRequestBody(req);
      const data = JSON.parse(body);

      const message: ClineMessage = {
        id: `cline_${Date.now()}`,
        timestamp: Date.now(),
        agent: "Cline",
        message: data.message || "",
        code: data.code,
        action: data.action,
      };

      clineQueue.push(message);

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          ok: true,
          messageId: message.id,
          queueSize: clineQueue.length,
        }),
      );
      return true;
    }

    // GET /api/cline/poll - Cline polls for messages from OpenClaw
    if (req.method === "GET" && url.pathname === "/api/cline/poll") {
      const since = parseInt(url.searchParams.get("since") || "0");

      const messages = clineQueue.filter(
        (m) => m.timestamp > since && m.agent !== "Cline", // Don't send back Cline's own messages
      );

      res.writeHead(200, {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      });
      res.end(
        JSON.stringify({
          ok: true,
          messages,
          serverTime: Date.now(),
        }),
      );
      return true;
    }

    // GET /api/cline/status - Check bridge status
    if (req.method === "GET" && url.pathname === "/api/cline/status") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          ok: true,
          queueSize: clineQueue.length,
          lastMessage: clineQueue[clineQueue.length - 1],
          uptime: process.uptime(),
        }),
      );
      return true;
    }

    // DELETE /api/cline/clear - Clear message queue
    if (req.method === "DELETE" && url.pathname === "/api/cline/clear") {
      const oldSize = clineQueue.length;
      clineQueue.length = 0;

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          ok: true,
          cleared: oldSize,
        }),
      );
      return true;
    }

    return false; // Not handled by this plugin
  });

  // Gateway WebSocket method for status checks
  api.registerGatewayMethod("cline.status", ({ respond }) => {
    respond(true, {
      ok: true,
      queueSize: clineQueue.length,
      latestMessage: clineQueue[clineQueue.length - 1],
      uptime: process.uptime(),
    });
  });

  // Gateway WebSocket method to send messages
  api.registerGatewayMethod("cline.send", ({ params, respond }) => {
    const messageId = `cline_${Date.now()}`;

    clineQueue.push({
      id: messageId,
      timestamp: Date.now(),
      agent: params.agent || "OpenClaw",
      message: params.message,
      code: params.code,
      action: params.action,
    });

    respond(true, {
      ok: true,
      messageId,
      queueSize: clineQueue.length,
    });
  });
}

function readRequestBody(req: any): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk: Buffer) => {
      body += chunk.toString();
    });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}
